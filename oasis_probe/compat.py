"""Narrow OASIS 0.2.6 quote rendering repair; installed source stays untouched.

Quote branch omits num_reports, causing UnboundLocalError if first in a feed,
or inheritance from a prior unrelated post. Initialise from this row before branches.
Repost branch still replaces it with the root count, preserving native semantics.
"""
import inspect
import textwrap
from oasis.social_platform.platform_utils import PlatformUtils


def install():
    original = PlatformUtils._add_comments_to_posts
    if getattr(original, '_quote_report_repair', False):
        return
    source = textwrap.dedent(inspect.getsource(original))
    anchor = '    for row in posts_results:\n'
    assert source.count(anchor) == 1
    repaired = source.replace(anchor, anchor +
        '        self.db_cursor.execute("SELECT num_reports FROM post WHERE post_id = ?", (row[0],))\n'
        '        num_reports = self.db_cursor.fetchone()[0]\n')
    namespace = {}
    exec(compile(repaired, '<oasis-quote-report-repair>', 'exec'), original.__globals__, namespace)
    replacement = namespace['_add_comments_to_posts']
    replacement._quote_report_repair = True
    PlatformUtils._add_comments_to_posts = replacement
