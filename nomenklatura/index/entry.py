import math
from typing import TYPE_CHECKING, Any, Dict, Generator, Generic, List, Optional, Tuple

from nomenklatura.entity import DS, E

if TYPE_CHECKING:
    from nomenklatura.index.index import Index


class IndexEntry(Generic[DS, E]):
    """A set of entities and a weight associated with a given term in the index."""

    __slots__ = "idf", "entities"

    def __init__(self) -> None:
        self.idf: float = 0.0
        self.entities: Dict[str, int] = dict()

    def add(self, entity_id: str, weight: float = 1.0) -> None:
        """Mark the given entity as relevant to the entry's token."""
        # This is insane and meant to trade perf for memory:
        if entity_id not in self.entities:
            self.entities[entity_id] = 0
        self.entities[entity_id] += 1

    def compute(self, index: "Index[DS, E]") -> None:
        """Compute weighted term frequency for scoring."""
        index_entities = float(len(index.terms))
        entities = len(self.entities)
        idf = ((index_entities - entities) + 0.5) / (entities + 0.5)
        self.idf = math.log(1 + idf)

    def frequencies(
        self, index: "Index[DS, E]"
    ) -> Generator[Tuple[str, float], None, None]:
        for entity_id, count in self.entities.items():
            if count == 0:
                continue
            terms = index.terms.get(entity_id, 0.0)
            tf = count / max(terms, index.min_terms)
            # tf = 1 + math.log(tf)
            yield entity_id, tf * self.idf

    def __repr__(self) -> str:
        return "<IndexEntry(%r)>" % len(self)

    def __len__(self) -> int:
        return len(self.entities)

    def to_dict(self) -> Dict[str, Any]:
        return {"entities": self.entities}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IndexEntry[DS, E]":
        obj = cls()
        obj.entities = data["entities"]
        return obj
