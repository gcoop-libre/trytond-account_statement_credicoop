# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.
from trytond.pool import Pool

from . import journal
from . import statement
from . import party

__all__ = ['register']


def register():
    Pool.register(
        journal.Journal,
        party.PartyIdentifier,
        statement.Statement,
        statement.ImportStatementStart,
        module='account_statement_credicoop', type_='model')
    Pool.register(
        statement.ImportStatement,
        module='account_statement_credicoop', type_='wizard')