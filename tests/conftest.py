"""Configure the same concrete application graph used by CLI and Web tests."""

from pathlib import Path

from rflp_lite.bootstrap.container import build_container


# A number of legacy unit tests instantiate application services directly.
# Keep that public construction path working while production entry points use
# the explicit container passed by the interface layer.
build_container(Path.cwd())
