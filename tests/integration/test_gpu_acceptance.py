from __future__ import annotations

import os
import shutil
import subprocess

import pytest


pytestmark = pytest.mark.gpu


@pytest.mark.skipif(
    os.getenv("AI4MBSE_GPU_ACCEPTANCE") != "1",
    reason="GPU acceptance test is opt-in and requires the integration workflow",
)
def test_gpu_runner_exposes_nvidia_device() -> None:
    executable = shutil.which("nvidia-smi")
    assert executable, "nvidia-smi is required on the GPU acceptance runner"

    result = subprocess.run(
        [
            executable,
            "--query-gpu=index,name,memory.total",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.stdout.strip(), "nvidia-smi reported no visible GPU"
