from nomenklatura.schema import attributes
from nomenklatura.query.util import parse_name, is_list, OP_SIM


class QueryNode(object):

    def __init__(self, parent, name, data):
        self.parent = parent
        self.data = value = data

        parts = parse_name(name)
        self.name, self.inverted, self._op = parts

        self.many = is_list(value)
        if self.many:
            value = None if not len(value) else value[0]

        if isinstance(value, dict):
            self.sort = value.pop('sort', None)
            self.limit = value.pop('limit', 15)
            if not self.many:
                self.limit = 1
            self.offset = value.pop('offset', 0)

        self.value = value
        self.attribute = attributes[self.name]

    @property
    def attributes(self):
        if self.name == 'id':
            return set()
        if self.name == '*':
            return set(attributes)
        if self.attribute is not None:
            return set([self.attribute])

    @property
    def root(self):
        return self.parent is None

    @property
    def op(self):
        if self.leaf and not self.blank:
            return self._op

    @property
    def blank(self):
        return self.value is None

    @property
    def leaf(self):
        return not isinstance(self.value, dict)

    @property
    def scored(self):
        if self.leaf:
            return self.op == OP_SIM
        if self.root:
            for child in self.children:
                if child.scored:
                    return True
        return False

    @property
    def filtered(self):
        if self.leaf:
            return self.value is not None
        for child in self.children:
            if child.filtered:
                return True
        return False

    @property
    def children(self):
        if self.leaf:
            return
        for name, data in self.value.items():
            yield QueryNode(self, name, data)

    def to_dict(self):
        data = {
            'name': self.name,
            'leaf': self.leaf,
            'many': self.many,
            'blank': self.blank,
            'filtered': self.filtered
        }
        if self.root:
            data['limit'] = self.limit
            data['offset'] = self.offset
            del data['name']
        if self.leaf:
            data['value'] = self.value if self.leaf else None
            data['op'] = self.op
            data['inverted'] = self.inverted
        else:
            data['children'] = [c.to_dict() for c in self.children]
        return data