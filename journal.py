# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.

from trytond.pool import PoolMeta
from trytond.model import fields


class Journal(metaclass=PoolMeta):
    __name__ = 'account.statement.journal'

    group_moves_by_account = fields.Boolean('Group moves by account',
        help='Group the statement lines by account when creating moves')

    @staticmethod
    def default_group_moves_by_account():
        return False
