# PV 3070 NiceHash Controller

Automatic PV-surplus control for one NVIDIA RTX 3070 running NiceHash Miner on Windows 10/11.

## Architecture

- **Shelly Pro 3EM**: supplies current PV/grid power information.
- **Controller**: Python service evaluates surplus, hysteresis, runtime and safety limits.
- **NVIDIA RTX 3070**: controlled through `nvidia-smi` power limits and temperature monitoring.
- **NiceHash Miner**: remains responsible for profitability, benchmarking and algorithm switching.

The controller deliberately does **not** implement its own algorithm/profit switching.

## Default control logic

- Start when PV surplus is at least **180 W for 3 minutes**.
- Stop when surplus falls below **110 W for 5 minutes**.
- Keep **40 W reserve** for the household.
- GPU target is dynamically limited to **100–180 W**, in 10 W steps.
- GPU temperature warning: **75 C**; critical stop: **80 C**.
- Shelly/GPU communication failures trigger a safe stop.
- `dry_run: true` is enabled initially.

## Requirements

- Windows 10/11 x64
- Python 3.11+
- NVIDIA driver with `nvidia-smi`
- NVIDIA RTX 3070
- NiceHash Miner installed
- Shelly Pro 3EM reachable over HTTP

NiceHash Miner is available from the official NiceHash repository: https://github.com/nicehash/NiceHashMiner

## Installation

1. Install Python 3.11+.
2. Install NVIDIA drivers and verify `nvidia-smi` works.
3. Install NiceHash Miner and complete its normal setup/benchmarking.
4. Copy `config.yaml.example` to `config.yaml` if desired, or edit the included config.
5. Set the Shelly IP and NiceHash installation path.
6. Run `python -m src.main` with `dry_run: true`.
7. Verify the reported surplus and GPU values.
8. Only then set `dry_run: false`.

## Manual run

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m src.main
```

## Windows Scheduled Task

Run `scripts\install_task.ps1` from an elevated PowerShell after testing interactively. The task starts the controller at boot.

## Safety

Do not use this software as the sole protection against electrical or thermal faults. The controller only manages software-level operating conditions. Hardware protections and NVIDIA driver protections remain mandatory.

## License

MIT
