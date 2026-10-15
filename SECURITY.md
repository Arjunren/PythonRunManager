# Security

## Local execution

PythonRunManager runs selected scripts and terminal commands as the Windows user who opened it. It is not a sandbox. Register trusted projects and review commands before execution. Adding a system executes it immediately; startup preferences can execute it on later launches.

Terminal commands can modify files, install packages, and access the network. The manager does not request elevation or store credentials.

## Boundaries and data

- Entry files must be `.py` files inside the registered project. Launch validation checks resolved paths, including links.
- Processes use argument lists and `shell=False`. The command terminal does not support shell operators or Windows batch wrappers.
- Stop force-terminates a tracked process tree. Applications must persist data safely; detached children may require separate cleanup.
- Settings contain project paths and preferences in the user's profile.
- Logs and command history can contain sensitive information. Input responses are excluded from history, but input is visible and child programs may echo it. Review exports before sharing them.
- Executables are unsigned. Download from this repository's Releases page and compare the published SHA-256 values.

## Reporting

For sensitive issues, use **Report a vulnerability** in the repository's Security tab if available. Otherwise, open an issue requesting a private reporting channel without publishing exploit details, secrets, or personal data.

Use the latest release for fixes. There is no guaranteed response or support schedule.
