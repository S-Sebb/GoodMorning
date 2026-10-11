"""One command dispatcher, with lazy imports and unchanged helper arguments."""
import argparse
from importlib import import_module
import sys

COMMANDS = {
    'setup': 'setup_check',
    'weather': 'weather',
    'news': 'news.news',
    'calendar': 'calendar.secretary_calendar',
    'state': 'records.state',
    'sessions': 'web.session_inventory',
    'inbox': 'records.inbox',
    'workflow': 'records.workflow',
    'daily': 'records.daily',
    'job': 'briefings.briefing_job',
    'stream': 'briefings.briefing_stream',
    'serve': 'web.briefing_server',
    'web': 'briefings.briefing_web',
    'admin': 'security.briefing_admin',
    'gateway': 'security.briefing_gateway',
    'runtime': 'security.briefing_runtime',
    'vault': 'security.briefing_vault',
    'reply-policy': 'reply_policy',
}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__, usage='%(prog)s COMMAND [arguments]')
    parser.add_argument('command', choices=COMMANDS)
    if not argv or argv[0] in ('-h', '--help') or argv[0] not in COMMANDS:
        parser.parse_args(argv)
    command = argv.pop(0)
    original = sys.argv
    try:
        sys.argv = [original[0] + ' ' + command, *argv]
        return import_module('goodmorning.' + COMMANDS[command]).main() or 0
    finally:
        sys.argv = original
