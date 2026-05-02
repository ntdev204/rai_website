from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from app.core.config import settings


@dataclass(frozen=True)
class SshTarget:
    name: str
    host: str
    port: int
    user: str


def get_available_targets() -> dict[str, SshTarget]:
    targets: dict[str, SshTarget] = {}

    if settings.SSH_JETSON_HOST and settings.SSH_JETSON_USER:
        targets["jetson"] = SshTarget(
            name="jetson",
            host=settings.SSH_JETSON_HOST,
            port=settings.SSH_JETSON_PORT,
            user=settings.SSH_JETSON_USER,
        )

    if settings.SSH_RASPI_HOST and settings.SSH_RASPI_USER:
        targets["raspi"] = SshTarget(
            name="raspi",
            host=settings.SSH_RASPI_HOST,
            port=settings.SSH_RASPI_PORT,
            user=settings.SSH_RASPI_USER,
        )

    return targets


class SshTerminalSession:
    def __init__(self, target: SshTarget) -> None:
        self.target = target
        self.process: asyncio.subprocess.Process | None = None
        self._stdout_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None

    async def start(self, emit: Any) -> None:
        ssh_command = [
            "ssh",
            "-tt",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            f"ConnectTimeout={int(settings.SSH_CONNECT_TIMEOUT_SEC)}",
            "-p",
            str(self.target.port),
            f"{self.target.user}@{self.target.host}",
        ]

        self.process = await asyncio.create_subprocess_exec(
            *ssh_command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        assert self.process.stdout is not None
        assert self.process.stderr is not None

        self._stdout_task = asyncio.create_task(self._pipe_stream(self.process.stdout, "stdout", emit))
        self._stderr_task = asyncio.create_task(self._pipe_stream(self.process.stderr, "stderr", emit))

    async def _pipe_stream(self, stream: asyncio.StreamReader, stream_name: str, emit: Any) -> None:
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                break
            await emit(
                {
                    "type": "output",
                    "stream": stream_name,
                    "data": chunk.decode("utf-8", errors="replace"),
                }
            )

    async def send(self, data: str) -> None:
        if not self.process or not self.process.stdin:
            return
        self.process.stdin.write(data.encode("utf-8"))
        await self.process.stdin.drain()

    async def wait(self) -> int | None:
        if not self.process:
            return None
        return await self.process.wait()

    async def close(self) -> None:
        if self.process and self.process.returncode is None:
            if self.process.stdin:
                self.process.stdin.close()
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=3)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()

        for task in (self._stdout_task, self._stderr_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
