import asyncio
import base64
import pymysql.cursors
import traceback
import xml.etree
import html

from html.parser import HTMLParser

class MLStripper(HTMLParser):
    def __init__(self):
        self.reset()
        self.strict = False
        self.convert_charrefs= True
        self.fed = []

    def handle_data(self, d):
        self.fed.append(d)

    def get_data(self):
        return ''.join(self.fed)

def remove_tags(text):
    s = MLStripper()
    s.feed(html.unescape(text))

    return s.get_data()

class Wiki:
    def __init__(self, bot):
        self.current_edit = {}
        self.bot = bot
        self.config = bot.config
        self.wikidb = None

    def connectDb(self):
        try:
            self.wikidb = pymysql.connect(
                host=self.config['wiki_mysql']['host'],
                user=self.config['wiki_mysql']['user'],
                password=self.config['wiki_mysql']['pass'],
                database=self.config['wiki_mysql']['db'])
        except pymysql.err.OperationalError as ex:
            print("Wiki: Error connecting to MySQL: {}".format(ex))

    async def fetch_edit(self):
        modifier = sm = s = ""
        send_to_staff = False

        try:
            self.connectDb()
            if self.wikidb is None:
                return False

            with self.wikidb.cursor() as cursor:
                sql = """SELECT
                         rc_user_text, rc_title,
                         rc_comment, rc_minor,
                         rc_new, rc_patrolled,
                         rc_old_len, rc_new_len,
                         rc_log_type
                         FROM recentchanges
                         WHERE rc_log_type
                         NOT IN ('block', 'renameusers', 'renameuser', 'newusers')
                         OR rc_log_type IS NULL
                         ORDER BY rc_id DESC LIMIT 1
                      """

                cursor.execute(sql)
                result = cursor.fetchone()

                text, title, comment, minor,  new, patrolled, old_len, new_len, log_type = result

                if self.current_edit == result:
                    return True

                # Don't spam every time we restart
                if not self.current_edit:
                    self.current_edit = result
                    return True
                else:
                    self.current_edit = result

                # Decode
                title = title.decode('utf-8')
                comment = comment.decode('utf-8')
                log_type= log_type.decode('utf-8')
                text = remove_tags(text.decode('utf-8'))
                length = len(text)
                if length > 50:
                    text = text[:50] + "..."

                # Format the output
                if log_type and 'rights' in log_type:
                    s = "{title}'s permissions were modified: {comment}".format(**locals())
                    send_to_staff = True
                elif log_type and 'upload' in log_type:
                    s = "{text} uploaded {title}: {comment}".format(**locals())
                else:
                    modifier = "edited"
                    if new == 1:
                        modifier = "created"
                    elif new_len == 0:
                        modifier = "modified"

                    if '_' in title:
                        title = title.replace('_', ' ')

                    if minor == 1:
                        s += "[minor] "

                    dif = ("%+d" % (new_len - old_len))
                    s += "{text} {modifier} page {title} ({dif}): {comment}".format(**locals())


                # Send it to the appropriate channel
                channel = self.config['channels']['ars_wiki']
                if send_to_staff:
                    channel = self.config['channels']['ars_wiki_staff']
                    if not patrolled:
                        sm += "[PENDING] "

                sm += s

                await self.bot.isend(channel, sm)
                return True
        except Exception:
            await self.bot.alert_error("Wiki exception: {}".format(traceback.format_exc()))
            return False
        finally:
            self.closeDb()

    async def check(self):
        await self.bot.discord.wait_until_ready()
        while not self.bot.discord.is_closed:
            if not await self.fetch_edit():
                await asyncio.sleep(30)
            else:
                await asyncio.sleep(int(self.config['forums']['check_rate']))

    def closeDb(self):
        if self.wikidb is not None:
            self.wikidb.close()
