# Copyright 2016 The Sysl Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License."""Super smart code writer."""

"""Diagramming utilities"""

import collections
import cStringIO
import itertools
import os
import re
import sys

import plantuml
import requests

import cache
import confluence
import simple_parser

def group_by(src, key):
  """Apply sorting and grouping in a single operation."""
  return itertools.groupby(sorted(src, key=key), key=key)


def fmt_app_name(appname):
  """Format an app name as a single string."""
  return ' :: '.join(appname.part)


def add_common_diag_options(argp):
  """Add common diagramming options to a subcommand parser."""
  argp.add_argument(
    '--title', '-t', type=lambda s: unicode(s, 'utf8'),
    help='diagram title')
  argp.add_argument(
    '--output', '-o',
    help='output file')
  argp.add_argument(
    '--plantuml', '-p',
    help=('base url of plantuml server (default: %(default)s; '
        'see http://plantuml.com/server.html#install for more info)'))
  argp.add_argument(
    '--verbose', '-v', action='store_true',
    help='Report each output.')
  argp.add_argument(
    '--expire-cache', action='store_true',
    help='Expire cache entries to force checking against real destination')
  argp.add_argument(
    '--dry-run', action='store_true',
    help="Don't perform confluence uploads, but show what would have happened")

  argp.add_argument(
    'modules', nargs='+',
    help='modules')


OutputArgs = collections.namedtuple('OutputArgs',
  'output plantuml verbose expire_cache dry_run')


def output_plantuml(args, puml_input):
  """Output a PlantUML diagram."""
  ext = os.path.splitext(args.output or '')[-1][1:]
  mode = {'png':'img', 'svg':'svg', 'uml':None, '':None}[ext]
  server = (args.plantuml or
    os.getenv('SYSL_PLANTUML', 'http://localhost:8080/plantuml'))
  if mode:
    def calc():
      puml = plantuml.PlantUML('{}/{}/'.format(server, mode))
      response = requests.get(puml.get_url(puml_input))
      response.raise_for_status()
      return response.content
    out = cache.get(mode + ':' + puml_input, calc)

  useConfluence = args.output.startswith('confluence://')

  if args.verbose:
    print args.output + '...' * useConfluence,
    sys.stdout.flush()

  if useConfluence:
    if confluence.upload_attachment(
        args.output, cStringIO.StringIO(out), args.expire_cache, args.dry_run
        ) is None:
      if args.verbose:
        print '\033[1;30m(no change)\033[0m',
    else:
      if args.verbose:
        print '\033[1;32muploaded\033[0m',
        if args.dry_run:
          print '... not really (dry-run)',
  else:
    (open(args.output, 'w') if args.output else sys.stdout).write(out)
    # (open(args.output + '.puml', 'w') if args.output else sys.stdout).write(puml_input)

  if args.verbose:
    print


class VarManager(object):
  """Synthesise a mapping from names to variables.

  This class is used to map arbitrary names, which may not be valid in some
  syntactic contexts, to more uniform names.
  """

  def __init__(self, newvar):
    self._symbols = {}
    self._newvar = newvar

  def __call__(self, name):
    """Return a variable name for a given name.

    Make sure the same name always maps to the same variable."""
    if name in self._symbols:
      return self._symbols[name]

    var = '_{}'.format(len(self._symbols))
    self._newvar(var, name)
    self._symbols[name] = var
    return var




class _FmtParser(simple_parser.SimpleParser):
  """Parse format strings used in project .sysl files."""
  # TODO: Document the format string sublanguage.

  def parse(self):
    """Top-level parse function."""
    if self.expansions():
      code = 'lambda **vars: ' + self.pop()
      #pdb.set_trace()
      return eval(code)  # pylint: disable=eval-used

  def expansions(self, term=u'$'):
    """Parse expansions."""
    result = [repr(u'')]
    while self.eat(ur'((?:[^%]|%[^(\n]|\n)*?)(?=' + term + ur'|%\()'):
      prefix = self.pop()
      prefix = re.sub(
        u'%(.)', ur'\1', prefix.replace(u'%%', u'\1')
        ).replace(u'\1', u'%')
      if prefix:
        result.append(repr(prefix))
      if self.eat(ur'%\('):
        if not self.eat(ur'(@?\w+)'):
          raise Exception('missing variable reference')
        var = cond = u"vars.get({!r}, '')".format(self.pop())

        if self.eat(ur'~/([^/]+)/'):
          cond = u're.search({!r}, {})'.format(
            self.pop().replace('\b', r'\b'), var)

        have = self.eat(ur'[?]')
        if have:
          if not self.expansions(ur'$|[|)]'):
            raise Exception('wat?')
          have = self.pop()

        have_not = self.eat(ur'\|')
        if have_not:
          if not self.expansions(ur'$|\)'):
            raise Exception('wat?')
          have_not = self.pop()

        if not self.eat(ur'\)'):
          raise Exception('unclosed expansion')

        result.append(u"({} if {} else {})".format(
          have or var, cond, have_not or repr('')))
      else:
        self.push(u'(' + u' + '.join(result) + u')')
        return True


def parse_fmt(text):
  """Parse a format string."""
  return _FmtParser(text)()


def attr_fmt_vars(*attrses, **kwargs):
  """Return a dict based attrs that is suitable for use in parse_fmt()."""
  fmt_vars = {}

  for attrs in attrses:
    if type(attrs).__name__ in ['MessageMap', 'MessageMapContainer']:
      for (name, attr) in attrs.iteritems():
        if attr.WhichOneof('attribute'):
          fmt_vars['@' + name] = getattr(attr, attr.WhichOneof('attribute'))
        else:
          fmt_vars['@' + name] = ''
    else:
      fmt_vars.update(attrs)

  fmt_vars.update(kwargs)

  return fmt_vars
