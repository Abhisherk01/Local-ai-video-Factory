//! Local AI Video Factory - Tauri 2 desktop shell (Phase 2).
//!
//! Responsibilities:
//! 1. Spawn the Python backend (`python -m laf.server`) as a managed child
//!    process bound to 127.0.0.1 on a random free port.
//! 2. Generate a per-session token, passed via the LAF_TOKEN env var
//!    (never logged, never written to disk by this side).
//! 3. Poll /health until the backend is ready (or fail honestly with the
//!    log file location).
//! 4. Expose `get_backend_info` IPC so the React UI learns the port/token.
//! 5. Kill the backend when the app exits.
//!
//! Known Phase 2 limitation (documented in README/ROADMAP): Python and the
//! backend package are resolved from the development layout - the repo
//! venv (../.venv/Scripts/python.exe) or the `py -3.12` launcher, overridable
//! with LAF_PYTHON. A packaged install flow (bundled runtime, tray lifecycle)
//! arrives with Phase 3+.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{Read, Write};
use std::net::TcpListener;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use rand::Rng;
use serde::Serialize;
use tauri::{Manager, RunEvent, State};

const HEALTH_TIMEOUT_SECS: u64 = 30;
const PROBE_INTERVAL_MS: u64 = 500;
const CREATE_NO_WINDOW: u32 = 0x0800_0000; // Windows: no console window for the backend

// ---------------------------------------------------------------------------
// Shared state
// ---------------------------------------------------------------------------

#[derive(Clone, Serialize)]
#[serde(rename_all = "snake_case", tag = "state")]
enum BackendStatus {
    Starting,
    Ready {
        port: u16,
        token: String,
        pid: Option<u32>,
    },
    Error {
        message: String,
    },
}

struct Shared {
    child: Mutex<Option<Child>>,
    status: Mutex<BackendStatus>,
}

impl Shared {
    fn new() -> Arc<Self> {
        Arc::new(Self {
            child: Mutex::new(None),
            status: Mutex::new(BackendStatus::Starting),
        })
    }

    fn set_status(&self, status: BackendStatus) {
        *self.status.lock().expect("status mutex poisoned") = status;
    }
}

// ---------------------------------------------------------------------------
// IPC command
// ---------------------------------------------------------------------------

#[tauri::command]
fn get_backend_info(shared: State<'_, Arc<Shared>>) -> BackendStatus {
    shared
        .status
        .lock()
        .expect("status mutex poisoned")
        .clone()
}

// ---------------------------------------------------------------------------
// Backend spawning
// ---------------------------------------------------------------------------

fn find_python() -> Result<PathBuf, String> {
    if let Ok(custom) = std::env::var("LAF_PYTHON") {
        let path = PathBuf::from(custom);
        if path.exists() {
            return Ok(path);
        }
        return Err(format!(
            "LAF_PYTHON is set to '{}' but that path does not exist.",
            path.display()
        ));
    }

    // Development layout: repo venv next to src-tauri/..
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let venv_python = manifest_dir
        .join("..")
        .join(".venv")
        .join("Scripts")
        .join("python.exe");
    if venv_python.exists() {
        return Ok(venv_python);
    }

    // py launcher (checked with a real `py -3.12 --version` call)
    let probe = Command::new("py")
        .arg("-3.12")
        .arg("--version")
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
    if matches!(probe, Ok(status) if status.success()) {
        return Ok(PathBuf::from("py"));
    }

    Err(
        "Python 3.12 not found. Create the repo venv (see INSTALLATION.md) \
         or set LAF_PYTHON to a Python 3.12 executable."
            .to_string(),
    )
}

fn free_port() -> Result<u16, String> {
    TcpListener::bind(("127.0.0.1", 0))
        .map_err(|error| format!("could not bind a free port: {error}"))?
        .local_addr()
        .map(|address| address.port())
        .map_err(|error| format!("could not read the free port: {error}"))
}

fn random_token() -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut rng = rand::rng();
    (0..32)
        .map(|_| HEX[rng.random_range(0..16)] as char)
        .collect()
}

struct SpawnedBackend {
    child: Child,
    port: u16,
    token: String,
    pid: Option<u32>,
}

/// Put the backend child into a Windows Job Object with KILL_ON_JOB_CLOSE.
///
/// Why (Phase 3 orphan fix): the backend is spawned with CREATE_NO_WINDOW,
/// which detaches it from our console - Ctrl+C on the dev terminal kills
/// the shell but never reaches the backend, and kill_backend() only runs
/// on the graceful exit path (RunEvent::Exit). With the job object, the
/// kernel closes our job handle when the shell exits for ANY reason
/// (graceful close, Ctrl+C, crash, taskkill) and terminates the backend
/// with it. kill_backend() remains the tidy first line of defense.
#[cfg(target_os = "windows")]
fn assign_backend_job_object(child: &Child) -> Result<(), String> {
    use std::os::windows::io::AsRawHandle;
    use windows_sys::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
        SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };

    unsafe {
        let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
        if job == std::mem::zeroed() {
            return Err("CreateJobObjectW failed".to_string());
        }
        let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        let ok = SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            &info as *const _ as *const core::ffi::c_void,
            std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
        );
        if ok == 0 {
            return Err("SetInformationJobObject failed".to_string());
        }
        let process_handle = child.as_raw_handle() as _;
        if AssignProcessToJobObject(job, process_handle) == 0 {
            return Err("AssignProcessToJobObject failed".to_string());
        }
        // The job handle is intentionally never closed: KILL_ON_JOB_CLOSE
        // fires when the shell process exits and releases it. One handle
        // per backend spawn, released by the kernel at exit.
    }
    Ok(())
}

fn spawn_backend(app: &tauri::AppHandle) -> Result<SpawnedBackend, String> {
    let python = find_python()?;

    let backend_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("backend");
    if !backend_dir.join("laf").join("server.py").exists() {
        return Err(format!(
            "backend package not found at {} (run from the repository).",
            backend_dir.display()
        ));
    }

    let data_dir = match std::env::var("LAF_DATA_DIR") {
        Ok(custom) => PathBuf::from(custom),
        Err(_) => app
            .path()
            .app_local_data_dir()
            .map_err(|error| format!("could not resolve the app data dir: {error}"))?,
    };
    std::fs::create_dir_all(&data_dir)
        .map_err(|error| format!("could not create the data dir: {error}"))?;

    let port = free_port()?;
    let token = random_token();

    let mut command = Command::new(&python);
    // The py launcher needs an explicit version switch.
    if python.file_name().and_then(|name| name.to_str()) == Some("py") {
        command.arg("-3.12");
    }
    command
        .args(["-m", "laf.server"])
        .arg("--port")
        .arg(port.to_string())
        .arg("--data-dir")
        .arg(&data_dir)
        .current_dir(&backend_dir)
        .env("LAF_TOKEN", &token);

    // Backend logs go to a per-session file in the data dir (never blocks,
    // inspectable after crashes). The token is never logged by the backend.
    let log_path = data_dir.join("backend.log");
    let log_file = std::fs::OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(true)
        .open(&log_path)
        .map_err(|error| format!("could not open the backend log file: {error}"))?;
    command.stdout(log_file.try_clone().map_err(|e| e.to_string())?);
    command.stderr(log_file);

    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(CREATE_NO_WINDOW);
    }

    let child = command.spawn().map_err(|error| {
        format!(
            "failed to launch {:?}: {error}. Check Python 3.12 setup (INSTALLATION.md).",
            python
        )
    })?;
    let pid = Some(child.id());

    // Non-fatal on failure: the graceful kill path still works; this is
    // the backstop for hard exits (see assign_backend_job_object docs).
    #[cfg(target_os = "windows")]
    {
        let _ = assign_backend_job_object(&child);
    }

    Ok(SpawnedBackend {
        child,
        port,
        token,
        pid,
    })
}

// ---------------------------------------------------------------------------
// Health probing
// ---------------------------------------------------------------------------

fn probe_health(port: u16) -> bool {
    use std::net::TcpStream;

    let mut stream = match TcpStream::connect(("127.0.0.1", port)) {
        Ok(stream) => stream,
        Err(_) => return false,
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(600)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(600)));

    let request = b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n";
    if stream.write_all(request).is_err() {
        return false;
    }

    let mut buffer = [0u8; 512];
    let mut head: Vec<u8> = Vec::new();
    loop {
        match stream.read(&mut buffer) {
            Ok(0) => break,
            Ok(count) => {
                head.extend_from_slice(&buffer[..count]);
                if head.len() > 4096 {
                    break;
                }
            }
            Err(_) => break,
        }
    }

    let text = String::from_utf8_lossy(&head);
    text.starts_with("HTTP/1.1 200") || text.starts_with("HTTP/1.0 200")
}

fn readiness_loop(shared: Arc<Shared>, port: u16, token: String, pid: Option<u32>) {
    let deadline = Instant::now() + Duration::from_secs(HEALTH_TIMEOUT_SECS);

    loop {
        // Early-exit check: if the backend process died, fail fast.
        {
            let mut guard = shared.child.lock().expect("child mutex poisoned");
            match guard.as_mut() {
                Some(child) => match child.try_wait() {
                    Ok(Some(status)) => {
                        drop(guard);
                        shared.set_status(BackendStatus::Error {
                            message: format!(
                                "the backend exited early ({}). See backend.log \
                                 inside the app data directory for details.",
                                status
                            ),
                        });
                        return;
                    }
                    Ok(None) => {}
                    Err(error) => {
                        drop(guard);
                        shared.set_status(BackendStatus::Error {
                            message: format!("could not query the backend process: {error}"),
                        });
                        return;
                    }
                },
                None => return, // already killed (app exiting)
            }
        }

        if probe_health(port) {
            shared.set_status(BackendStatus::Ready { port, token, pid });
            return;
        }

        if Instant::now() > deadline {
            shared.set_status(BackendStatus::Error {
                message: format!(
                    "the backend did not become healthy within {} seconds. \
                     See backend.log inside the app data directory.",
                    HEALTH_TIMEOUT_SECS
                ),
            });
            return;
        }

        std::thread::sleep(Duration::from_millis(PROBE_INTERVAL_MS));
    }
}

fn kill_backend(shared: &Arc<Shared>) {
    let mut guard = match shared.child.lock() {
        Ok(guard) => guard,
        Err(_) => return, // poisoned during shutdown: nothing safe to do
    };
    if let Some(mut child) = guard.take() {
        let _ = child.kill();
        let _ = child.wait();
    }
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

fn main() {
    let shared = Shared::new();

    tauri::Builder::default()
        .manage(shared.clone())
        .invoke_handler(tauri::generate_handler![get_backend_info])
        .setup(move |app| {
            match spawn_backend(app.handle()) {
                Ok(spawned) => {
                    *shared.child.lock().expect("child mutex poisoned") = Some(spawned.child);
                    std::thread::spawn(move || {
                        readiness_loop(shared.clone(), spawned.port, spawned.token, spawned.pid);
                    });
                }
                Err(message) => {
                    shared.set_status(BackendStatus::Error { message });
                }
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building the tauri application")
        .run(|app_handle, event| {
            if let RunEvent::Exit = event {
                // State<'_, Arc<Shared>> derefs to Arc<Shared>; pass the inner
                // reference that kill_backend expects.
                kill_backend(app_handle.state::<Arc<Shared>>().inner());
            }
        });
}
