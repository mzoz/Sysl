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

import cPickle
import hashlib
import os
import sqlite3
import sys
import time


class Connection(object):

  DBPATH = os.path.expandvars('/tmp/.sysl.cache.db')

  _SCHEMA = """\
    CREATE TABLE version (
      __nonce__ PRIMARY KEY DEFAULT 0,
      ver
    );

    CREATE TABLE cache (
      key PRIMARY KEY,
      pickled,
      last_access
    );

    CREATE TABLE cache_size (
      key PRIMARY KEY REFERENCES cache(key),
      size
    );

    CREATE INDEX cache__last_access ON cache (last_access);
    """

  def __init__(self):
    self.conn = None

  def _connect(self):
    self.conn = sqlite3.connect(self.DBPATH)
    self.conn.text_factory = str
    return self.conn

  @property
  def connection(self):
    while self.conn is None:
      self._connect()

      schema_ver = hashlib.sha256(self._SCHEMA).hexdigest()

      try:
        [(db_ver,)] = self.conn.execute('SELECT ver FROM version').fetchall()
      except:
        db_ver = None

      if db_ver == schema_ver:
        break

      self.conn = None
      os.remove(self.DBPATH)

      self._connect()

      self.conn.executescript(self._SCHEMA)
      self.conn.execute('INSERT INTO version (ver) VALUES (?)', (schema_ver,))

    return self.conn

  def __call__(self, sql, args=()):
    return self.connection.execute(sql, args)


CONN = Connection()


def _hash(key):
  return hashlib.sha256(key).hexdigest()


# force_miss is only for internal use by put().
def get(key, calc, force_miss=False):
  key = _hash(key)

  with CONN.connection:
    cur = CONN('SELECT pickled FROM cache WHERE key = ?', (key,))
    result = cur.fetchall()
    last_access = time.time()

    if result and not force_miss:
      [(pickled,)] = result
      value = cPickle.loads(pickled)
      CONN('UPDATE cache SET last_access = ? WHERE key = ?', (last_access, key))
    else:
      value = calc()
      pickled = cPickle.dumps(value)
      CONN('INSERT OR REPLACE INTO cache (key, pickled, last_access) VALUES'
        ' (?, ?, ?)', (key, pickled, last_access))
      CONN('INSERT OR REPLACE INTO cache_size (key, size) VALUES (?, ?)',
        (key, len(pickled)))

    # Clear out stale entries.
    day = 24 * 60 * 60
    CONN('DELETE FROM cache WHERE last_access < ?', (last_access - 30 * day,))
    CONN('DELETE FROM cache_size'
      ' WHERE NOT EXISTS (SELECT * FROM cache WHERE key = ?)', (key,))

    # Keep cache small.
    limit = 100 << 20
    [(total_size,)] = CONN('SELECT SUM(size) FROM cache_size').fetchall()
    if total_size > limit:
      condemned = []
      stale = CONN('SELECT key, size\n'
             'FROM cache NATURAL JOIN cache_size\n'
             'ORDER BY last_access')
      for (key, size) in stale:
        condemned.append((key,))
        total_size -= size
        if total_size < limit:
          break

      del stale

      CONN.connection.executemany('DELETE FROM cache_size WHERE key = ?',
        condemned)
      CONN.connection.executemany('DELETE FROM cache WHERE key = ?',
        condemned)

  return value


def put(key, value):
  get(key, lambda: value, force_miss=True)


def expire(key):
  key = _hash(key)

  with CONN.connection:
    CONN('DELETE FROM cache WHERE key = ?', (key,))
    CONN('DELETE FROM cache_size WHERE key = ?', (key,))
