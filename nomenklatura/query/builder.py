from collections import OrderedDict

from normality import normalize
from sqlalchemy import exists, and_, func
from sqlalchemy.orm import aliased

from nomenklatura.core import db, url_for
from nomenklatura.schema import attributes
from nomenklatura.model.statement import Statement
from nomenklatura.model.context import Context
from nomenklatura.query.util import OP_EQ, OP_LIKE, OP_IN, OP_NOT, OP_SIM, OP_NIN


# TODO: split out the parts that affect graph filtering and
# results processing / reconstruction.

# TODO: optional/forbidden
# same_as = aliased(Statement)
# return q.filter(~exists().where(and_(
#     same_as._attribute == attributes.same_as.name,
#     same_as._value == stmt.subject,
#     same_as.subject == self.other
# )))

class QueryBuilder(object):

    def __init__(self, dataset, parent, node):
        self.dataset = dataset
        self.parent = parent
        self.node = node
        self.results = {}

    @property
    def children(self):
        if not hasattr(self, '_children'):
            self._children = []
            for child_node in self.node.children:
                qb = QueryBuilder(self.dataset, self, child_node)
                self._children.append(qb)
        return self._children

    def _add_statement(self, q):
        """ Generate a linked statement that can be used in any
        part of the query. """
        stmt = aliased(Statement)
        ctx = aliased(Context)
        q = q.filter(stmt.context_id == ctx.id)
        q = q.filter(stmt.dataset_id == self.dataset.id)
        q = q.filter(ctx.active == True) # noqa
        return stmt, q

    def filter_value(self, q, filter_stmt):
        if self.node.op == OP_EQ:
            q = q.filter(filter_stmt._value == self.node.value)
        elif self.node.op == OP_NOT:
            q = q.filter(filter_stmt._value != self.node.value)
        elif self.node.op == OP_IN:
            q = q.filter(filter_stmt._value.in_(self.node.data))
        elif self.node.op == OP_NIN:
            q = q.filter(~filter_stmt._value.in_(self.node.data))
        elif self.node.op == OP_LIKE:
            value = '%%%s%%' % normalize(self.node.value)
            q = q.filter(filter_stmt.normalized.like(value))
        elif self.node.op == OP_SIM:
            value = normalize(self.node.value)[:254]
            field = func.left(filter_stmt.normalized, 254)

            # calculate the similarity percentage
            rel = func.greatest(max(float(len(self.node.value)), 1.0),
                                func.length(filter_stmt.normalized))
            distance = func.levenshtein(field, value)
            score = ((rel - distance) / rel) * 100.0
            score = func.max(score).label('score')

            q = q.add_column(score)
            q = q.having(score >= 1)
            q = q.order_by(score.desc())
        return q

    def filter_subject(self, q, filter_stmt):
        if self.node.op == OP_EQ:
            q = q.filter(filter_stmt.subject == self.node.value)
        elif self.node.op == OP_NOT:
            q = q.filter(filter_stmt.subject != self.node.value)
        elif self.node.op == OP_IN:
            q = q.filter(filter_stmt.subject.in_(self.node.data))
        elif self.node.op == OP_NIN:
            q = q.filter(~filter_stmt.subject.in_(self.node.data))
        return q

    def filter(self, q, subject):
        """ Apply filters to the given query recursively. """
        if not self.node.filtered:
            return q

        filter_stmt, q = self._add_statement(q)
        if self.node.attribute:
            q = q.filter(filter_stmt._attribute == self.node.attribute.name)

        if self.node.leaf:
            # The child will be value-filtered directly.
            q = q.filter(subject == filter_stmt.subject)
            return self.filter_value(q, filter_stmt)

        for child in self.children:
            if child.node.name == 'id':
                # If the child is a query for an ID, don't recurse.
                q = q.filter(subject == filter_stmt.subject)
                q = child.filter_subject(q, filter_stmt)
            else:
                # Inverted queries apply to non-leaf children only.
                col_subj, col_val = filter_stmt.subject, filter_stmt._value
                if self.node.inverted:
                    col_subj, col_val = col_val, col_subj
                q = q.filter(subject == col_subj)
                q = child.filter(q, col_val)

        return q

    def filter_query(self, parents=None):
        """ An inner query that is used to apply any filters, limits
        and offset. """
        q = db.session.query()
        stmt, q = self._add_statement(q)
        q = q.add_column(stmt.subject)

        if parents is not None and self.node.attribute:
            parent_stmt, q = self._add_statement(q)
            q = q.filter(stmt.subject == parent_stmt._value)
            q = q.filter(parent_stmt._attribute == self.node.attribute.name)
            q = q.filter(parent_stmt.subject.in_(parents))

        q = self.filter(q, stmt.subject)
        q = q.group_by(stmt.subject)
        # q = q.order_by(stmt.subject.asc())
        if self.node.sort == 'random':
            q = q.order_by(func.random())

        if self.node.root and self.node.limit is not None:
            q = q.limit(self.node.limit)
            q = q.offset(self.node.offset)

        return q

    def nested(self):
        """ A list of all sub-entities for which separate queries will
        be conducted. """
        for child in self.children:
            if child.node.leaf or not child.node.attribute:
                continue
            if child.node.attribute.data_type == 'entity':
                yield child

    def project(self):
        """ Figure out which attributes should be returned for the current
        level of the query. """
        attrs = set()
        for child in self.children:
            if child.node.leaf:
                attrs.update(child.node.attributes)
        attrs = attrs if len(attrs) else attributes
        skip_nested = [n.node.attribute for n in self.nested()]
        return [a.name for a in attrs if a not in skip_nested]

    def base_object(self, data):
        """ Make sure to return all the existing filter fields
        for query results. """
        obj = {
            'id': data.get('id'),
            'api_url': url_for('entities.view', dataset=self.dataset.slug,
                               id=data.get('id')),
            'parent_id': data.get('parent_id')
        }

        if 'score' in data:
            obj['score'] = data.get('score')

        for child in self.children:
            if self.node.blank:
                obj[child.node.name] = child.node.data
        return obj

    def get_node(self, name):
        """ Get the node for a given name. """
        for child in self.children:
            if child.node.name == name:
                return child.node
        return None if name == '*' else self.get_node('*')

    def data_query(self, parents=None):
        """ Generate a query for any statement which matches the criteria
        specified through the filter query. """
        filter_q = self.filter_query(parents=parents)
        q = db.session.query()
        stmt, q = self._add_statement(q)

        filter_sq = filter_q.subquery()
        q = q.filter(stmt.subject == filter_sq.c.subject)

        projected_attributes = self.project()
        q = q.filter(stmt._attribute.in_(projected_attributes))

        q = q.add_column(stmt.subject.label('id'))
        q = q.add_column(stmt._attribute.label('attribute'))
        q = q.add_column(stmt._value.label('value'))

        if self.node.scored:
            score = filter_sq.c.score.label('score')
            q = q.add_column(score)
            q = q.order_by(score.desc())

        if parents is not None and self.node.attribute:
            parent_stmt, q = self._add_statement(q)
            q = q.filter(stmt.subject == parent_stmt._value)
            q = q.filter(parent_stmt._attribute == self.node.attribute.name)
            q = q.add_column(parent_stmt.subject.label('parent_id'))

        q = q.order_by(filter_sq.c.subject.desc())
        q = q.order_by(stmt.created_at.asc())
        return q

    def execute(self, parents=None):
        """ Run the data query and construct entities from it's results. """
        results = OrderedDict()
        for row in self.data_query(parents=parents):
            data = row._asdict()
            id = data.get('id')
            if id not in results:
                results[id] = self.base_object(data)

            value = data.get('value')
            attr = attributes[data.get('attribute')]
            if attr.data_type not in ['type', 'entity']:
                conv = attr.converter(self.dataset, attr)
                value = conv.deserialize_safe(value)

            node = self.get_node(data.get('attribute'))
            if attr.many if node is None else node.many:
                if attr.name not in results[id]:
                    results[id][attr.name] = []
                results[id][attr.name].append(value)
            else:
                results[id][attr.name] = value
        return results

    def collect(self, parents=None):
        """ Given re-constructed entities, conduct queries for child
        entities and merge them into the current level's object graph. """
        results = self.execute(parents=parents)
        ids = results.keys()
        for child in self.nested():
            attr = child.node.attribute.name
            for child_data in child.collect(parents=ids).values():
                parent_id = child_data.pop('parent_id')
                if child.node.many:
                    if attr not in results[parent_id]:
                        results[parent_id][attr] = []
                    results[parent_id][attr].append(child_data)
                else:
                    results[parent_id][attr] = child_data
        return results

    def query(self):
        results = []
        for result in self.collect().values():
            result.pop('parent_id')
            if not self.node.many:
                return result
            results.append(result)
        return results