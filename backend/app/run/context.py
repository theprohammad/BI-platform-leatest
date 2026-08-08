"""RunContext: everything one analysis run needs, passed explicitly.

No module-level clients, no globals — this is what makes runs reproducible
(rule 2), testable (fake providers inject here), and later parallelizable
across workers.
"""
import uuid
from dataclasses import dataclass, field

from app.core.ledger import CostLedger
from app.memory.shared_memory import SharedMemory
from app.providers.llm.base import LLMProvider
from app.providers.llm.router import LLMRouter
from app.providers.search.base import SearchProvider


@dataclass
class RunContext:
    request: object
    llm: LLMRouter
    search: SearchProvider
    ledger: CostLedger
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    memory: SharedMemory = field(default_factory=SharedMemory)


def build_run_context(request, llm_provider: LLMProvider, search_provider: SearchProvider) -> RunContext:
    ledger = CostLedger()
    run_id = uuid.uuid4().hex[:12]
    router = LLMRouter(llm_provider, ledger=ledger, run_id=run_id)
    return RunContext(request=request, llm=router, search=search_provider,
                      ledger=ledger, run_id=run_id)
