# Linux Benchmark GUI

A modern, responsive graphical user interface for the **Linux Benchmark Library (`linux-benchmark-lib`)**. Built with Python and **Qt (PySide6)**, it provides a powerful dashboard for orchestrating benchmarks, visualizing real-time progress, and analyzing results.

## 🚀 Features

*   **Real-time Dashboard:** Monitor benchmark execution with live progress tracking, journal updates, and log streaming.
*   **Visual Configuration:** Create and edit complex benchmark configurations using intuitive forms instead of editing JSON/YAML manually.
*   **Plugin Management:** Browse, install, and manage workload plugins directly from the UI.
*   **Results Analysis:** View historical benchmark runs and visualize metrics (integration pending).
*   **System Diagnostics:** "Doctor" mode to verify system health and prerequisites before running heavy workloads.
*   **Theme Support:** multiple built-in themes (Dark, Warm, Graphite/Teal) for a comfortable user experience.

## 🛠️ Technology Stack

*   **Language:** Python 3.12+
*   **GUI Framework:** [Qt for Python (PySide6)](https://doc.qt.io/qtforpython/)
*   **Architecture:** MVVM (Model-View-ViewModel) pattern for clean separation of concerns.
*   **Styling:** QSS (Qt Style Sheets) for theming.

## 📦 Prerequisites

This GUI is designed to work as a frontend for the `linux-benchmark-lib` ecosystem.

*   Python 3.12 or higher.
*   `linux-benchmark-lib` installed in the environment.
*   `PySide6` for the UI rendering.

## 📥 Installation

### As part of the main library (Recommended)
Usually, this package is installed automatically when you install the main library with the GUI extra (if available) or dev dependencies.

### Standalone Development Setup
If you are developing on the GUI specifically:

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/miciav/linux-benchmark-gui.git
    cd linux-benchmark-gui
    ```

2.  **Create a virtual environment:**
    ```bash
    uv venv
    source .venv/bin/activate
    ```

3.  **Install dependencies:**
    You will need the core library accessible. If you are working in the monorepo context, ensure `linux-benchmark-lib` is installed in editable mode.
    ```bash
    pip install PySide6
    # Install the core library (adjust path as needed)
    pip install -e ../linux-benchmark-lib
    ```

## 🖥️ Usage

To launch the application, run the entry point module:

```bash
python -m lb_gui.main
```

Or if exposed via the main CLI tool (depending on integration):
```bash
lb gui
```

## 🏗️ Architecture Overview

The project follows a strict **MVVM (Model-View-ViewModel)** architecture:

*   **`views/`**: Qt Widgets that define the UI layout and appearance. They observe ViewModels.
*   **`viewmodels/`**: Classes that hold the state for specific views and handle UI logic. They interact with Services.
*   **`services/`**: Business logic layer. Wrappers around the core `lb_app` or `lb_controller` functionality to keep the UI decoupled from the backend implementation.
*   **`widgets/`**: Reusable custom UI components (e.g., `JournalTable`, `LogViewer`).
*   **`resources/`**: Assets, icons, and QSS theme files.

### Directory Structure

```text
lb_gui/
├── main.py              # Application entry point
├── app.py               # Dependency injection container (ServiceContainer)
├── resources/           # Themes (*.qss) and assets
├── services/            # Bridges to core library logic
├── viewmodels/          # UI Logic & State
├── views/               # PySide6 Widgets (Screens)
├── widgets/             # Reusable components
├── windows/             # Main application window
└── workers/             # Background threads (QThread) for long-running tasks
```

## 🤝 Contributing

Contributions are welcome!

1.  **Fork** the repository.
2.  Create a **feature branch**.
3.  Commit your changes following the [Conventional Commits](https://www.conventionalcommits.org/) standard.
4.  Push to the branch and open a **Pull Request**.

Please ensure you follow the existing MVVM patterns and style guidelines (Black, Flake8).

## 📄 License

This project is part of the `linux-benchmark-lib` ecosystem. Please refer to the main repository for license details.
