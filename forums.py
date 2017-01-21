import asyncio
import base64
import psycopg2
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

class Forum:
    def __init__(self, bot):
        self.read_posts = []
        self.bot = bot
        self.config = bot.config
        self.forumdb = None

    def connectDb(self):
        try:
            self.forumdb = psycopg2.connect(
                user=self.config['forum_mysql']['user'],
                dbname=self.config['forum_mysql']['db'])
        except Exception as ex:
            print("Error connecting to PostgreSQL: {}".format(ex))

    async def fetch_post(self):
        try:
            self.connectDb()
            if self.forumdb is None: return False
            with self.forumdb.cursor() as cursor:
                sql = """SELECT
                         phpbb3_posts.post_id,
                         phpbb3_users.username,
                         phpbb3_topics.topic_title,
                         phpbb3_forums.forum_id, phpbb3_topics.topic_id,
                         phpbb3_posts.post_text AS post_text_trimmed,
                         (SELECT COUNT(*) FROM phpbb3_posts WHERE phpbb3_posts.topic_id = (SELECT topic_id FROM phpbb3_posts ORDER BY post_id DESC LIMIT 1)) AS post_reply_number,
                         phpbb3_posts.post_id AS number_id,
                         COALESCE(phpbb3_ranks.rank_title, 'Registered User') AS group_title
                         FROM phpbb3_posts
                         INNER JOIN phpbb3_users ON phpbb3_posts.poster_id = phpbb3_users.user_id
                         INNER JOIN phpbb3_forums ON phpbb3_forums.forum_id = phpbb3_posts.forum_id
                         INNER JOIN phpbb3_topics ON phpbb3_topics.topic_id = phpbb3_posts.topic_id
                         LEFT JOIN phpbb3_ranks ON phpbb3_ranks.rank_id = phpbb3_users.user_rank
                         WHERE phpbb3_forums.forum_id NOT IN (1, 13, 16, 30, 31, 34)
                         AND phpbb3_posts.post_visibility = 1
                         ORDER BY phpbb3_posts.post_id DESC LIMIT 1
                      """

                cursor.execute(sql)
                result = cursor.fetchone()

                pid, tusername, ttitle, fid, tid, post_text, replynum, numberid, group = result

                if pid in self.read_posts:
                    return True

                self.read_posts.append(pid)

                if len(self.read_posts) == 1:
                    return True

                post_text = remove_tags(post_text)
                length    = len(post_text)
                post_text = post_text[:50]
                if length > len(post_text):
                    post_text += "..."

                replymsg = "New topic!"
                if replynum > 0:
                    replymsg = "New reply!"

                sm = """__**{ttitle}**__ - **{replymsg}** - {tusername} *({group})*
https://thesirenboard.com/forums/viewtopic.php?f={fid}&t={tid}&p={numberid}#p{numberid}

```{post_text}```""".format(**locals())

                await self.bot.isend(self.config['channels']['ars_forums'], sm)
                return True
        except Exception:
            await self.bot.alert_error("Forum exception: {}".format(traceback.format_exc()))
            return False
        finally:
            self.closeDb()

    async def check(self):
        await self.bot.discord.wait_until_ready()
        while not self.bot.discord.is_closed:
            if not await self.fetch_post():
                await asyncio.sleep(30)
            else:
                await asyncio.sleep(int(self.config['forums']['check_rate']))

    def closeDb(self):
        if self.forumdb is not None:
            self.forumdb.close()
