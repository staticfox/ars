import asyncio
from datetime import datetime
from dateutil.relativedelta import relativedelta
import dateparser
import time
import re
import sqlite3

class DCManager:
    def __init__(self, bot):
        self.bot = bot
        self.config = bot.config
        self.discord = self.bot.discord
        self.control_channels = [self.config['channels']['dc_mod_control'], self.config['channels']['ars_debug']]
        self.conn = None
        self.create_db()


    def create_db(self):
        self.conn = sqlite3.connect('db/ban.db')
        c = self.conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS bans (
            ban_id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
            server_id INTEGER NOT NULL,
            target_id INTEGER NOT NULL,
            target_name TEXT NOT NULL,
            banner_id INTEGER NOT NULL,
            banner_name TEXT NOT NULL,
            reason INTEGER DEFAULT NULL,
            expires INTEGER DEFAULT 0,
            ban_type TEXT NOT NULL
        )''')
        self.conn.commit()


    def add_db_ban(self, server, target, banner, reason, expires, ban_type):
        escaped = re.sub("'", "''", reason)
        c = self.conn.cursor()
        c.execute('''
            INSERT INTO bans
            (server_id, target_id, target_name, banner_id, banner_name, reason, expires, ban_type)
            VALUES
            ({}, {}, '{}', {}, '{}', '{}', {}, '{}')
        '''.format(server,
                   target.id, re.sub("'", "''", target.display_name),
                   banner.id, re.sub("'", "''", banner.display_name),
                   escaped, expires, ban_type))
        self.conn.commit()


    async def check_for_unbans(self):
        epoch = int(abs(time.mktime(datetime.now().timetuple())))
        c = self.conn.cursor()
        c.execute('''
            SELECT
            server_id, target_id, target_name, banner_id,
            banner_name, reason, expires, ban_type
            FROM bans WHERE expires < {}
        '''.format(epoch))
        for row in c.fetchall():
            await self.unban(row[0], row[1], row[2], row[3], row[4], row[5], row[7], 'expiring')
        c.execute('''DELETE FROM bans WHERE expires < {}'''.format(epoch))
        self.conn.commit()


    async def unban(self, server_id, target_id, target_name, banner_id, banner_name, reason, ban_type, why):
        server_node = None
        for server in self.discord.servers:
            if str(server.id) == str(server_id):
                server_node = server
                break

        if not server_node:
            await self.bot.alert_error('Unable to find server {}'.format(server_id))
            return

        target_node = None
        for member in server_node.members:
            if str(member.id) == str(target_id):
                target_node = member
                break

        if not target_node:
            await self.bot.alert_error('Unable to find member {}'.format(target_id))
            return

        for role in server_node.roles:
            if role in target_node.roles:
                await self.discord.remove_roles(target_node, role)
            try:
                target_node.roles.remove(role)
            except ValueError:
                continue

        log_message = "[unban] {} {} ban for {} ({}) by {} ({}) ({})".format(
            why, ban_type, target_name, target_id, banner_name, banner_id, reason
        )

        await self.bot.isend(self.config['channels']['dc_mod_logs'], log_message)


    async def loop(self):
        await self.bot.discord.wait_until_ready()
        while not self.bot.discord.is_closed:
            await self.check_for_unbans()
            await asyncio.sleep(3)


    async def do_shadow_ban(self, server, target, reason):
        shadowban_role = None
        for role in server.roles:
            if 'shadow' in role.name.lower():
                shadowban_role = role
                break

        if not shadowban_role:
            await self.bot.alert_error("BUG: Unable to find shadow ban role!")
            return

        for role in server.roles:
            if role in target.roles:
                await self.discord.remove_roles(target, role)
            try:
                target.roles.remove(role)
            except ValueError:
                continue

        await self.discord.add_roles(target, shadowban_role)
        await self.discord.send_message(target, reason)


    async def do_timeout(self, server, target, reason):
        timeout_role = None
        for role in server.roles:
            if 'timeout' in role.name.lower():
                timeout_role = role
                break

        if not timeout_role:
            await self.bot.alert_error("BUG: Unable to find timeout ban role!")
            return

        for role in server.roles:
            if role in target.roles:
                await self.discord.remove_roles(target, role)
            try:
                target.roles.remove(role)
            except ValueError:
                continue

        await self.discord.add_roles(target, timeout_role)
        await self.discord.send_message(target, reason)


    async def move_to_timeout_voice(self, server, target):
        banned_channel = None
        for channel in server.channels:
            if channel.type.voice and str(channel.id) == '263542134026665985':
                banned_channel = channel
                break

        if not banned_channel:
            await self.bot.alert_error("BUG: Unable to find banned_channel!")
            return

        for channel in server.channels:
            if target in channel.voice_members and channel != banned_channel:
                await self.bot.debug_notify("Moving {} to {}".format(target.display_name, banned_channel.name))
                await self.discord.move_member(target, banned_channel)


    async def parse_unban(self, origin, ban_id):
        try:
            ban_int = int(ban_id)
        except ValueError:
            await self.bot.isend(origin, 'Invalid Ban ID')
            return

        if ban_int <= 0:
            await self.bot.isend(origin, 'Ban ID must be a positive number')
            return

        c = self.conn.cursor()
        c.execute('''
            SELECT
            server_id, target_id, target_name, banner_id,
            banner_name, reason, expires, ban_type
            FROM bans WHERE ban_id = {}
        '''.format(ban_int))
        rows = c.fetchall()

        if len(rows) == 0:
            await self.bot.isend(origin, 'Ban ID {} not found'.format(ban_int))
            return

        for row in rows:
            await self.bot.isend(origin, 'Unbanning {}...'.format(row[2]))
            await self.unban(row[0], row[1], row[2], row[3], row[4], row[5], row[7], 'removing')

        c.execute('''DELETE FROM bans WHERE ban_id = {}'''.format(ban_int))
        self.conn.commit()


    async def show_bans(self, origin):
        attrs = ['years', 'months', 'days', 'hours', 'minutes', 'seconds']
        human_readable = lambda delta: ['%d %s' % (getattr(delta, attr), getattr(delta, attr) > 1 and attr or attr[:-1]) for attr in attrs if getattr(delta, attr)]

        c = self.conn.cursor()
        c.execute('''
            SELECT
            ban_id, target_id, target_name, banner_id,
            banner_name, reason, expires, ban_type
            FROM bans
        ''')
        rows = c.fetchall()

        if len(rows) == 0:
            await self.bot.isend(origin, 'No bans in place')
        else:
            await self.bot.isend(origin, '{} ban{}:'.format(len(rows), 's' if len(rows) != 1 else ''))
            for ban in rows:
                t = datetime.fromtimestamp(int(ban[6]))
                rd = relativedelta(t, datetime.now())
                time_readable_ = human_readable(rd)
                time_readable = ' '.join(time_readable_)

                await self.bot.isend(origin, 'Ban ID: {}\nType: {}\nExpires: {}\nModerator: {} ({})\nUser: {} ({})\nReason: {}\n\n'.format(
                    ban[0], ban[7], time_readable, ban[4], ban[3], ban[2], ban[1], ban[5]
                ))


    async def parse_ban(self, origin, ban_type, banner, server, target, ban_time, message):
        attrs = ['years', 'months', 'days', 'hours', 'minutes', 'seconds']
        human_readable = lambda delta: ['%d %s' % (getattr(delta, attr), getattr(delta, attr) > 1 and attr or attr[:-1]) for attr in attrs if getattr(delta, attr)]

        dt = dateparser.parse(ban_time)

        if not dt:
            await self.bot.isend(origin, 'Unable to parse time')
            return

        future = int(abs(time.mktime(dt.timetuple())))
        epoch = int(abs(time.mktime(datetime.now().timetuple())))

        rd = relativedelta(datetime.now(), dt)
        time_readable = human_readable(rd)

        seconds = epoch - future

        if seconds <= 0:
            await self.bot.isend(origin, 'Unable to parse time (underflow)')
            return

        new_message = ""
        if not message:
            if 'shadow' in ban_type:
                new_message = "You have been temporarily banned from Discord"
            elif 'timeout' in ban_type:
                new_message = "You have been temporarily timedout from Discord"
            else:
                await self.bot.alert_error("BUG: Received invalid parse_ban() argument!")
                new_message = "You have been temporarily banned from Discord"
        else:
            new_message = message

        target_nodes = []
        for member in server.members:
            if target.lower() == member.display_name.lower() or target.lower() == str(member.id):
                target_nodes = [member]
                break

            if target.lower() in member.display_name.lower():
                target_nodes.append(member)

        if len(target_nodes) < 1:
            await self.bot.isend(origin, 'Unable to find user {}'.format(target))
            return

        if len(target_nodes) > 1:
            await self.bot.isend(origin, 'Found multiple users for user {}, {}'.format(
                target, [node.display_name for node in target_nodes]
            ))
            return

        assert(len(target_nodes)) == 1

        target_node = target_nodes[0]

        action = 'timed out'
        if 'shadow' in ban_type:
            action = 'shadow banned'

        log_message = "[ban] {} ({}) has {} {} ({}) for {}. ({})".format(
            banner.display_name, banner.id, action, target_node.display_name,
            target_node.id, ' '.join(time_readable), new_message
        )

        new_message = new_message.strip().lstrip()
        new_message += " (Expires in {})".format(' '.join(time_readable))

        if 'shadow' in ban_type:
            await self.do_shadow_ban(server, target_node, new_message)
            self.add_db_ban(server.id, target_node, banner, new_message, epoch + seconds, 'Shadow Ban')
        else:
            await self.do_timeout(server, target_node, new_message)
            self.add_db_ban(server.id, target_node, banner, new_message, epoch + seconds, 'Timeout')

        await self.move_to_timeout_voice(server, target_node)

        await self.bot.isend(self.config['channels']['dc_mod_logs'], log_message)


    async def on_message(self, message):
        timeout_bans = ['!timeout', '!addtimeout', '!to']
        shadow_bans = ['!sb', '!shadow', '!shadowban']
        showbans = ['!bans', '!showbans', '!listbans']
        unban_cmd = ['!unban', '!ub']

        if str(message.author.id) == str(self.discord.user.id):
            return

        if message.channel and message.channel.id in self.control_channels:
            parts = message.content.split(' ')
            if len(parts) == 0:
                return # ???

            cmd = parts[0]

            if len(parts) >= 3:
                if cmd.lower() in timeout_bans or cmd.lower() in shadow_bans:
                    ban_type = ''
                    if cmd.lower() in shadow_bans:
                        ban_type = 'shadow'
                    else:
                        ban_type = 'timeout'

                    target = parts[1]
                    time = parts[2]
                    reason = ' '.join(parts[3:])
                    await self.parse_ban(message.channel, ban_type, message.author, message.server, target, time, reason)
                elif cmd.lower() in showbans:
                    await self.show_bans(message.channel.id)
                elif cmd.lower() in unban_cmd:
                    ban_id = parts[1]
                    await self.parse_unban(message.channel.id, ban_id)
            elif len(parts) >= 2:
                if cmd.lower() in unban_cmd:
                    ban_id = parts[1]
                    await self.parse_unban(message.channel.id, ban_id)
            else:
                if cmd.lower() in showbans:
                    await self.show_bans(message.channel.id)
