from typing import List
from nomenklatura.entity import CompositeEntity as Entity

from nomenklatura.matching.features.dates import key_day_matches, key_year_matches
from nomenklatura.matching.features.names import first_name_match, family_name_match
from nomenklatura.matching.features.names import name_levenshtein, name_match
from nomenklatura.matching.features.names import name_token_overlap
from nomenklatura.matching.features.misc import phone_match, email_match
from nomenklatura.matching.features.misc import identifier_match, birth_place
from nomenklatura.matching.features.misc import gender_mismatch, country_mismatch
from nomenklatura.matching.features.misc import schema_match

Encoded = List[float]

# TODO: introduce name length as a feature?????

FEATURES = [
    name_match,
    name_token_overlap,
    name_levenshtein,
    phone_match,
    email_match,
    identifier_match,
    key_day_matches,
    key_year_matches,
    first_name_match,
    family_name_match,
    birth_place,
    gender_mismatch,
    country_mismatch,
    schema_match,
]


def encode_pair(left: Entity, right: Entity) -> Encoded:
    """Encode the comparison between two entities as a set of feature values."""
    return [f(left, right) for f in FEATURES]
