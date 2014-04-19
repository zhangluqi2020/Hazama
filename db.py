﻿import sqlite3
import sys
import os
import shutil
import time
import richtagparser
import logging


# template used to format txt file
default_tpl = '''***{0[title]}***
[Date: {0[datetime]}]

{0[text]}\n\n\n\n'''


class Nikki:
    """This class hold a SQLite3 database,handling save/read/import/export.

    Each Table's function:
    Nikki: All diary saved here.(every one has all data except format/tag info).
    Nikki_Tags: Connecting tags to diary.
    Tags: All tags' body saved here.
    TextFormat: Connecting format info to diary.Format info itself also saved here.
    """

    def __str__(self):
        return '%s diary in database' % self.count()

    def __init__(self, db_path):
        self.setinstance(self)
        self.filepath = db_path
        self.conn = sqlite3.connect(db_path)
        self.exe = self.conn.execute
        self.conn.execute('CREATE TABLE IF NOT EXISTS Tags'
                          '(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE)')
        self.conn.execute('CREATE TABLE IF NOT EXISTS Nikki'
                          '(id INTEGER PRIMARY KEY, datetime TEXT NOT NULL, '
                          'plaintext INTEGER NOT NULL, text TEXT NOT NULL, '
                          'title TEXT NOT NULL)')
        self.conn.execute('CREATE TABLE IF NOT EXISTS Nikki_Tags'
                          '(nikkiid INTEGER NOT NULL REFERENCES Nikki(id) '
                          'ON DELETE CASCADE, tagid INTEGER NOT NULL,'
                          'PRIMARY KEY(nikkiid, tagid))')
        self.conn.execute('CREATE TABLE IF NOT EXISTS TextFormat'
                          '(nikkiid INTEGER NOT NULL REFERENCES Nikki(id) '
                          'ON DELETE CASCADE, start INTEGER NOT NULL, '
                          'length INTEGER NOT NULL, type INTEGER NOT NULL)')
        self.conn.execute('CREATE TRIGGER IF NOT EXISTS autodeltag AFTER '
                          'DELETE ON Nikki_Tags BEGIN   DELETE FROM Tags '
                          'WHERE (SELECT COUNT(*) FROM Nikki_Tags WHERE '
                          'Nikki_Tags.tagid=Tags.id)==0;  END')
        self.conn.execute('PRAGMA foreign_keys = ON')
        logging.info(str(self))

    def __getitem__(self, id):
        L = self.conn.execute('SELECT * FROM Nikki '
                              'WHERE id = ?', (id,)).fetchone()
        if not L:
            raise IndexError('id is not in database')
        tags = self.conn.execute('SELECT tagid FROM Nikki_Tags WHERE '
                                 'nikkiid = ?', (id,))
        taglst = [self.gettag(i[0]) for i in tags]
        tagstr = ' '.join(taglst) + ' ' if len(taglst) >= 1 else ''

        return dict(id=L[0], datetime=L[1], plaintext=L[2], text=L[3],
                    title=L[4], tags=tagstr)

    def reconnect(self, db_path):
        self.close()
        self.filepath = db_path
        self.conn = sqlite3.connect(db_path)
        self.exe = self.conn.execute

    def close(self):
        self.conn.close()

    def importXml(self, xmlpath):
        "Import CintaNotes/Hazama XML file,will not appear in main program."

        def trans_date(datetime):
            d, t = datetime.split('T')
            return (d[:4] + '/' + d[4:6] + '/' + d[6:] + ' '  # date
                    + t[:2] + ':' + t[2:4])  # time

        import xml.etree.ElementTree as ET

        tree = ET.parse(xmlpath)
        root = tree.getroot()
        Hxml = True if 'nikkichou' in str(root) else False

        if Hxml:
            startindex = 2
        else:  # CintaNotes XML
            startindex = 1 if root.find('tags') else 0

        # save tags into Tags Table.its index is always 0 in root
        if root.find('tags'):
            for t in root[0]:
                tag = (t.attrib['name'],)
                try:
                    self.conn.execute('INSERT INTO Tags VALUES(NULL,?)', tag)
                except Exception:
                    logging.warning('Failed adding tag: %s' % tag)
            self.commit()

        id = self.getnewid()  # the first column in Nikki Table
        index = startindex
        for i in range(startindex, len(root)):
            nikki = root[i].attrib
            text = root[i].text if root[i].text else ' '
            plain = int(nikki.get('plainText', 0))
            # import nikki itself into Nikki Table
            datetime = nikki['datetime'] if Hxml else trans_date(nikki['created'])
            values = (datetime, plain, text, nikki['title'])
            self.conn.execute('INSERT INTO Nikki VALUES(NULL,?,?,?,?)',
                              values)
            # import tags if nikki has
            if nikki['tags']:
                for tag in nikki['tags'].split():
                    values = (id, self.conn.execute('SELECT id FROM '
                                                    'Tags WHERE name=?', (tag,)).fetchone()[0])
                    self.conn.execute('INSERT INTO Nikki_Tags VALUES(?,?)',
                                      values)
            # import formats if nikki has rich text
            if not plain:
                if not Hxml:
                    parser = richtagparser.RichTagParser(strict=False)
                    parser.myfeed(id, text, self.conn)
                    text = parser.getstriped()
                else:
                    for f in root[1]:
                        if int(f.attrib['index']) == index:
                            values = (id, f.attrib['start'],
                                      f.attrib['length'], f.attrib['type'])
                            self.conn.execute('INSERT INTO TextFormat VALUES '
                                              '(?,?,?,?)', values)

            id += 1
            index += 1

        self.commit()

    def exportXml(self, xmlpath):
        """Export XML file,will not appear in main program."""
        import xml.etree.ElementTree as ET

        root = ET.Element('nikkichou')
        tags = ET.SubElement(root, 'tags')
        reachedTags = set()
        formats = ET.SubElement(root, 'formats')

        for e in enumerate(self.sorted('datetime'), 2):
            index, n = e  # index just connect a rich nikki to its formats
            nikki = ET.SubElement(root, 'nikki')
            for attr in ['title', 'datetime', 'tags']:
                nikki.set(attr, n[attr])
            nikki.set('plainText', str(n['plaintext']))
            nikki.text = n['text']
            # save reatched tags to set
            if n['tags']:
                for t in n['tags'].split(): reachedTags.add((t))
            # save format if current nikki has
            if not n['plaintext']:
                for r in self.getformat(n['id']):
                    format = ET.SubElement(formats, 'format')
                    for i in enumerate(['start', 'length', 'type']):
                        format.set('index', str(index))
                        format.set(i[1], str(r[i[0]]))

        for t in reachedTags:
            tag = ET.SubElement(tags, 'tag')
            tag.set('name', t)

        tree = ET.ElementTree(root)
        tree.write(xmlpath, encoding='utf-8')

    def exporttxt(self, txtpath, selected=None):
        """Export to TXT file using template(string format).
        When selected is a list contains nikki data,only export diary in list."""
        file = open(txtpath, 'w', encoding='utf-8')
        try:
            with open('template.txt', encoding='utf-8') as f:
                tpl = f.read()
        except OSError:
            logging.info('Use default template')
            tpl = default_tpl
        for n in (self.sorted('datetime', False) if selected is None
                   else selected):
            file.write(tpl.format(n))
        file.close()
        logging.info('Export succeed')

    def sorted(self, orderby, reverse=True, *, tagid=None, search=None):
        if tagid and (search is None):  # only fetch nikki whose tagid matchs
            where = ('WHERE id IN (SELECT nikkiid FROM Nikki_Tags WHERE '
                     'tagid=%i) ') % tagid
        elif search and (tagid is None):
            where = ('WHERE datetime LIKE "%%%s%%" OR text LIKE "%%%s%%" '
                     'OR title LIKE "%%%s%%"') % ((search,) * 3)
        elif search and tagid:
            where = ('WHERE (id IN (SELECT nikkiid FROM Nikki_Tags WHERE '
                     'tagid=%i)) AND (datetime LIKE "%%%s%%" OR '
                     'text LIKE "%%%s%%" OR title LIKE "%%%s%%")' %
                     ((tagid,) + (search,) * 3))
        else:
            where = ''

        if orderby == 'length':
            orderby = 'LENGTH(text)'
        cmd = ('SELECT * FROM Nikki ' + where + 'ORDER BY ' +
               orderby + (' DESC' if reverse else ''))
        for L in self.conn.execute(cmd):
            tags = self.conn.execute('SELECT tagid FROM Nikki_Tags WHERE '
                                     'nikkiid = ?', (L[0],))

            taglst = [self.gettag(i[0]) for i in tags]
            tagstr = ' '.join(taglst) + ' ' if len(taglst) >= 1 else ''
            yield dict(id=L[0], datetime=L[1], plaintext=L[2], text=L[3],
                       title=L[4], tags=tagstr)

    def delete(self, id):
        self.conn.execute('DELETE FROM Nikki WHERE id = ?', (id,))
        logging.info('Nikki deleted (ID: %s)' % id)
        self.commit()

    def commit(self):
        self.conn.commit()

    def count(self):
        return self.conn.execute('SELECT COUNT(id) FROM Nikki').fetchone()[0]

    def gettag(self, tagid=None, *, getcount=False):
        if tagid:  # get tags by id
            return self.conn.execute('SELECT name FROM Tags WHERE '
                                     'id = ?', (tagid,)).fetchone()[0]
        else:  # get all tags
            if getcount:  # get with counts.used in TList
                result = self.conn.execute('SELECT Tags.id,Tags.name,(SELECT '
                                           'COUNT(*) FROM Nikki_Tags WHERE Nikki_Tags.tagid=Tags.id) '
                                           'FROM Tags ORDER BY Tags.name')

                return result
            else:  # get without counts.used in tag completer
                result = self.conn.execute('SELECT name FROM Tags')
                return [n[0] for n in result]

    def getformat(self, id):
        return self.conn.execute('SELECT start,length,type FROM TextFormat '
                                 'WHERE nikkiid=?', (id,))

    def save(self, new, id, datetime, html, title, tags, plaintxt):
        id = self.getnewid() if new else id

        parser = richtagparser.QtHtmlParser()
        formats = parser.myfeed(html)
        plain = not formats
        values = ((None, datetime, plain, plaintxt, title) if new else
                  (datetime, plain, plaintxt, title, id))
        cmd = ('INSERT INTO Nikki VALUES(?,?,?,?,?)' if new else
               'UPDATE Nikki SET datetime=?, plaintext=?, '
               'text=?, title=? WHERE id=?')
        try:
            self.exe(cmd, values)
        except Exception:
            logging.warning('Failed saving Nikki (ID: %s)' % id)
            return
        else:
            logging.info('Nikki saved (ID: %s)' % id)
        # formats processing
        if not new:  # delete existed format information
            try:
                self.exe('DELETE FROM TextFormat WHERE nikkiid=?', (id,))
            except Exception:
                pass
        for i in formats:
            cmd = 'INSERT INTO TextFormat VALUES(?,?,?,?)'
            self.exe(cmd, (id,) + i)
        # tags processing
        if tags is not None:  # tags modified
            if not new:  # if diary isn't new,delete its tags first
                self.exe('DELETE FROM Nikki_Tags WHERE nikkiid=?', (id,))
            for t in tags:
                try:
                    self.exe('INSERT INTO Tags VALUES(NULL,?)', (t,))
                except Exception:
                    pass
            self.commit()
            for t in tags:
                cmd = 'SELECT id FROM Tags WHERE name=?'
                tagid = self.exe(cmd, (t,)).fetchone()[0]
                self.exe('INSERT INTO Nikki_Tags VALUES(?,?)', (id, tagid))
        self.commit()
        return id

    def getnewid(self):
        maxid = self.conn.execute('SELECT max(id) FROM Nikki').fetchone()[0]
        return maxid + 1 if maxid else 1

    @classmethod
    def setinstance(cls, instance):
        cls.instance = instance

    @classmethod
    def getinstance(cls):
        return cls.instance


def list_backups():
    files = sorted(os.listdir('backup'))
    fil = lambda x: len(x)>10 and x[4]==x[7]=='-' and x[10]=='_'
    return [i for i in files if fil(i)]


def restore_backup(bk_name, db_path):
    logging.info('Restore backup: %s', bk_name)
    bk_path = os.path.join('backup', bk_name)
    shutil.copyfile(bk_path, db_path)
    Nikki.getinstance().reconnect(db_path)


def check_backup(db_path):
    """Check backups and do if necessary.Delete old backups."""
    if not os.path.isdir('backup'): os.mkdir('backup')
    backups = list_backups()
    fmt = '%Y-%m-%d'
    today = time.strftime(fmt)
    try:
        newest = backups[-1]
    except IndexError:  # empty directory
        newest = ''
    if newest.split('_')[0] != today:  # new day
        # make new backup
        nikki = Nikki.getinstance()
        shutil.copyfile(db_path, os.path.join('backup',
                                              today+'_%d.db' % nikki.count()))
        logging.info('Everyday backup succeed')
        # delete old backups
        weekbefore = time.strftime(fmt, time.localtime(int(time.time())-604800))
        for dname in backups:
            if dname < weekbefore:
                os.remove(os.path.join('backup', dname))
            else:
                break
