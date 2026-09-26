#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri::Manager;
use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::CommandEvent;

/// Intenta arrancar el backend Python como sidecar `binaries/Ainslup --headless`.
/// En dev (sin sidecar empaquetado) no falla: la UI apunta a
/// http://127.0.0.1:18000 que puedes levantar con `cli_entry.py --headless`.
fn spawn_backend(app: &tauri::AppHandle) {
    let sidecar = app.shell().sidecar("Ainslup");
    let cmd = match sidecar {
        Ok(c) => c,
        Err(e) => {
            eprintln!("[ainslup] sidecar no disponible (dev?): {e}");
            return;
        }
    };
    let cmd = cmd.args(["--headless"]);
    let (_rx, _child) = match cmd.spawn() {
        Ok(pair) => pair,
        Err(e) => {
            eprintln!("[ainslup] no se pudo lanzar backend: {e}");
            return;
        }
    };
    // Log de stderr del backend sin bloquear.
    tauri::async_runtime::spawn(async move {
        let mut rx = _rx;
        while let Some(ev) = rx.recv().await {
            if let CommandEvent::Stderr(line) = ev {
                eprintln!("[ainslup-backend] {}", String::from_utf8_lossy(&line));
            }
        }
    });
    // `_child` se mantiene vivo mientras la app corre (sidecar supervisado).
    std::mem::forget(_child);
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            // Segunda instancia: enfocar ventana principal.
            if let Some(win) = app.get_webview_window("main") {
                let _ = win.set_focus();
                let _ = win.unminimize();
            }
        }))
        .setup(|app| {
            spawn_backend(app.handle());
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error running AINSLUP app");
}
