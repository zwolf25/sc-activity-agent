//! Desktop shell: starts the bundled agent program, shows its console in a window and keeps it running from the tray.
use std::fs::{self, OpenOptions};
use std::io::{Read, Write};
use std::net::TcpStream;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::menu::{CheckMenuItem, Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Manager, RunEvent, WebviewUrl};
use tauri_plugin_autostart::ManagerExt;

struct Agent {
    child: Mutex<Option<Child>>,
    port: Mutex<Option<u16>>,
    awake: Mutex<Option<Child>>,
}

fn data_dir(app: &AppHandle) -> PathBuf {
    app.path().app_data_dir().expect("app data dir")
}

fn sidecar_path() -> PathBuf {
    let exe = std::env::current_exe().expect("current exe");
    exe.parent().expect("exe dir").join(if cfg!(windows) { "agent-core.exe" } else { "agent-core" })
}

fn port_open(port: u16) -> bool {
    TcpStream::connect_timeout(&([127, 0, 0, 1], port).into(), Duration::from_millis(300)).is_ok()
}

fn read_port(dir: &Path) -> Option<u16> {
    fs::read_to_string(dir.join("port")).ok()?.trim().parse().ok()
}

/// Ask a running agent to stop. Quiet when nothing answers.
fn request_shutdown(port: u16) {
    if let Ok(mut s) = TcpStream::connect_timeout(&([127, 0, 0, 1], port).into(), Duration::from_millis(500)) {
        let _ = s.set_read_timeout(Some(Duration::from_secs(2)));
        let _ = s.write_all(b"POST /shutdown HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 0\r\nConnection: close\r\n\r\n");
        let mut sink = Vec::new();
        let _ = s.read_to_end(&mut sink);
    }
}

fn stop_agent(app: &AppHandle) {
    let state = app.state::<Agent>();
    let port = state.port.lock().unwrap().or_else(|| read_port(&data_dir(app)));
    if let Some(p) = port {
        request_shutdown(p);
        let end = Instant::now() + Duration::from_secs(5);
        while port_open(p) && Instant::now() < end {
            std::thread::sleep(Duration::from_millis(100));
        }
    }
    let child = state.child.lock().unwrap().take();
    if let Some(mut c) = child {
        let _ = c.kill();
    }
}

fn start_agent(app: &AppHandle) -> std::io::Result<()> {
    let dir = data_dir(app);
    fs::create_dir_all(&dir)?;
    if let Some(p) = read_port(&dir) {
        if port_open(p) {
            request_shutdown(p); // a copy left over from a crash or an update: replace it
            std::thread::sleep(Duration::from_secs(1));
        }
    }
    let _ = fs::remove_file(dir.join("port"));
    let log = OpenOptions::new().create(true).append(true).open(dir.join("agent.log"))?;
    let mut cmd = Command::new(sidecar_path());
    cmd.arg("--data-dir").arg(&dir).arg("run").env("SC_AGENT_PACKAGED", "1")
        .stdin(Stdio::null()).stdout(log.try_clone()?).stderr(log);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000); // no console window
    }
    *app.state::<Agent>().child.lock().unwrap() = Some(cmd.spawn()?);
    Ok(())
}

/// Keep the Mac from idle-sleeping while plugged in: plans only run while the machine is awake, and each sleep shifts them later.
/// `caffeinate -w` exits when this app does, so nothing is left behind. macOS only; the choice is remembered in `keep-awake`.
fn set_awake(app: &AppHandle, on: bool) {
    let _ = fs::write(data_dir(app).join("keep-awake"), if on { "1" } else { "0" });
    let state = app.state::<Agent>();
    let mut slot = state.awake.lock().unwrap();
    if let Some(mut c) = slot.take() {
        let _ = c.kill();
    }
    if on && cfg!(target_os = "macos") {
        *slot = Command::new("caffeinate").args(["-i", "-s", "-w", &std::process::id().to_string()]).spawn().ok();
    }
}

fn awake_wanted(app: &AppHandle) -> bool {
    fs::read_to_string(data_dir(app).join("keep-awake")).map(|s| s.trim() != "0").unwrap_or(true)
}

fn show_window(app: &AppHandle) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.show();
        let _ = w.unminimize();
        let _ = w.set_focus();
    }
}

fn build_tray(app: &AppHandle) -> tauri::Result<()> {
    let open = MenuItem::with_id(app, "open", "Open console", true, None::<&str>)?;
    let login = CheckMenuItem::with_id(app, "login", "Start at login", true, app.autolaunch().is_enabled().unwrap_or(false), None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Quit (stops the agent)", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&open, &login, &quit])?;
    let login_item = login.clone();
    let awake = CheckMenuItem::with_id(app, "awake", "Keep Mac awake (while plugged in)", true, awake_wanted(app), None::<&str>)?;
    #[cfg(target_os = "macos")]
    menu.insert(&awake, 2)?;
    let awake_item = awake.clone();
    TrayIconBuilder::with_id("agent")
        .icon(app.default_window_icon().cloned().expect("icon"))
        .tooltip("SC Activity Agent")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(move |app, e| match e.id.as_ref() {
            "open" => show_window(app),
            "login" => {
                let al = app.autolaunch();
                let _ = if al.is_enabled().unwrap_or(false) { al.disable() } else { al.enable() };
                let _ = login_item.set_checked(al.is_enabled().unwrap_or(false));
            }
            "awake" => {
                let on = !awake_wanted(app);
                set_awake(app, on);
                let _ = awake_item.set_checked(on);
            }
            "quit" => {
                stop_agent(app);
                app.exit(0);
            }
            _ => {}
        })
        .on_tray_icon_event(|t, e| {
            if let TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, .. } = e {
                show_window(t.app_handle());
            }
        })
        .build(app)?;
    Ok(())
}

/// Wait for the agent to publish its port and answer, then point the window at its console.
fn open_console_when_ready(app: AppHandle, hidden: bool) {
    std::thread::spawn(move || {
        let dir = data_dir(&app);
        let end = Instant::now() + Duration::from_secs(90);
        while Instant::now() < end {
            if let Some(p) = read_port(&dir) {
                if port_open(p) {
                    *app.state::<Agent>().port.lock().unwrap() = Some(p);
                    if let Some(w) = app.get_webview_window("main") {
                        if let Ok(u) = format!("http://127.0.0.1:{p}/").parse() {
                            let _ = w.navigate(u);
                        }
                        if !hidden {
                            let _ = w.show();
                        }
                    }
                    return;
                }
            }
            std::thread::sleep(Duration::from_millis(300));
        }
        if let Some(w) = app.get_webview_window("main") {
            let _ = w.show(); // the loading page stays; agent.log in the data folder says why
        }
    });
}

pub fn run() {
    let hidden = std::env::args().any(|a| a == "--hidden");
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| show_window(app)))
        .plugin(tauri_plugin_autostart::init(tauri_plugin_autostart::MacosLauncher::LaunchAgent, Some(vec!["--hidden"])))
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .manage(Agent { child: Mutex::new(None), port: Mutex::new(None), awake: Mutex::new(None) })
        .on_window_event(|w, e| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = e {
                api.prevent_close(); // the agent keeps working from the tray
                let _ = w.hide();
            }
        })
        .setup(move |app| {
            let handle = app.handle().clone();
            // First launch turns "start at login" on: plans only run while the app is running.
            let flag = data_dir(&handle).join("first-run-done");
            if !flag.exists() {
                let _ = fs::create_dir_all(data_dir(&handle));
                let _ = handle.autolaunch().enable();
                let _ = fs::write(&flag, "1");
            }
            build_tray(&handle)?;
            set_awake(&handle, awake_wanted(&handle));
            if let Err(e) = start_agent(&handle) {
                eprintln!("could not start the agent program: {e}");
            }
            if app.get_webview_window("main").is_none() {
                tauri::WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into())).title("SC Activity Agent").build()?;
            }
            open_console_when_ready(handle, hidden);
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("build app");
    app.run(|app, event| {
        match event {
            RunEvent::Exit => stop_agent(app),
            // Clicking the Dock or Finder icon while the window is hidden in the tray.
            #[cfg(target_os = "macos")]
            RunEvent::Reopen { .. } => show_window(app),
            _ => {}
        }
    });
}
