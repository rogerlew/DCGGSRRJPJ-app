from dataclasses import dataclass
from typing import Optional


@dataclass
class Run:
    run_enum: Optional[int] = None
    total_iterations: int = 50
    run_name: str = ""
