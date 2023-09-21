# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.

from trytond.pool import Pool
from . import account
from . import journal
from . import party
from . import statement


def register():
    Pool.register(
        account.Move,
        journal.StatementJournal,
        party.PartyIdentifier,
        statement.Statement,
        statement.ImportStatementStart,
        statement.PreloadedCardLoading,
        statement.PreloadedCardLoadingLine,
        module='account_statement_credicoop', type_='model')
    Pool.register(
        statement.PreloadedCardLoading2,
        module='account_statement_credicoop', type_='model',
        depends=['cooperative_ar'])
    Pool.register(
        statement.ImportStatement,
        module='account_statement_credicoop', type_='wizard')
