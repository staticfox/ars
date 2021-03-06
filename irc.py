from discord import PrivateChannel
import asyncio
import re
import time
import select
import socket
import sys

class IRCManager:
    def __init__(self, bot):
        self.bot = bot
        self.config = bot.config
        self.discord = self.bot.discord
        self.ident = self.config['irc']['ident']
        self.botnick = self.config['irc']['nick']
        self.real = self.config['irc']['realname']
        self.server = self.config['irc']['server']
        self.port = self.config['irc']['port']
        self.ircchannels = self.config['irc']['channels']
        self.ircaccount = self.config['irc']['account']
        self.ircpass = self.config['irc']['password']
        self.authserv = self.config['irc']['nickserv']
        self.irc_general_relay = self.config['irc']['relaychannel']
        self.irc_mapping_relay = self.config['irc']['mappingchannel']
        self.ircsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.ircsock.settimeout(0)
        self.ischecked = False
        self.buffer = b''
        self.length = None
        self.readready = False
        self.writeready = False
        self.sendbuf = []

    def privmsg(self, target, data):
        self.sendbuf.append("PRIVMSG %s :%s\n" % (target, data))

    async def onprivmsg(self, nick, channel, message):
        formatted = "[IRC] {}: {}".format(nick, message)
        if 'mapping' in channel:
            await self.bot.isend(self.config['channels']['ars_mapping'], formatted)
        else:
            await self.bot.isend(self.config['channels']['ars_general'], formatted)

    async def irc_both(self, message):
        chans = [self.config['channels']['ars_general'], self.config['channels']['ars_mapping']]
        for chan in chans:
            await self.bot.isend(chan, message)

    def idandjoin(self):
        if self.ircchannels:
            for channel in self.ircchannels:
                self.sendbuf.append("JOIN {}\n".format(channel))
        if self.ircaccount and self.authserv:
            self.privmsg(self.authserv, "LOGIN {} {}".format(self.ircaccount, self.ircpass))

    async def dc_callback(self):
        self.ircsock.close()
        time.sleep(10)
        self.ircsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.ircsock.settimeout(0)
        asyncio.ensure_future(self.loop())

    def socksend(self, data):
        d = data.encode('utf-8')
        try:
            self.ircsock.send(d)
        except BlockingIOError as e:
            print("socksend: {}".format(e))
            pass

    def decode_irc_string(self, string):
        try:
            return string.decode('UTF-8')
        except UnicodeDecodeError:
            try:
                return string.decode('iso-8859-1')
            except UnicodeDecodeError:
                return string.decode('ascii', 'ignore')

    async def relay_discord_general(self, content, message):
        m = "<{}> {}".format(message.author.name, content)
        self.privmsg(self.irc_general_relay, m)

    async def relay_discord_mapping(self, content, message):
        m = "<{}> {}".format(message.author.name, content)
        self.privmsg(self.irc_mapping_relay, m)

    async def on_message(self, message):
        if str(message.author.id) == str(self.bot.discord.user.id):
            return

        if isinstance(message.channel, PrivateChannel):
            return

        new_message = str(message.content)

        regex = re.compile("<@!(.+?)>")
        matches = regex.findall(new_message)

        def name_from_id(member_id):
            for server in self.discord.servers:
                for member in server.members:
                    if member_id == str(member.id):
                        return "@{}".format(member.display_name)
            return '@Unknown'

        for match in matches:
            new_name = name_from_id(match)
            new_message = re.sub(regex, new_name, new_message, 1)

        if message.channel.name == 'general':
            await self.relay_discord_general(new_message, message)
        elif message.channel.name == 'mapping':
            await self.relay_discord_mapping(new_message, message)

    async def connect(self):
        self.ischecked = False
        try:
            self.ircsock.connect((self.server, self.port))
        except BlockingIOError as e:
            if e.errno != 115:
                print("connect: {}".format(e))
            pass

        self.sendbuf.append("USER " + self.ident + " " + self.botnick + " " + self.botnick + " :" + self.real + " \n")
        self.sendbuf.append("NICK " + self.botnick + "\n")

        if self.ircpass and self.ircpass != "":
            self.sendbuf.append("PASS " + self.ircpass + "\n")

        return True

    async def loop(self):
        await self.bot.discord.wait_until_ready()
        self.readready = False
        self.writeready = False
        self.buffer = b''
        self.length = None
        while not await self.connect():
            await self.connect()
            await asyncio.sleep(.1)

        while not self.bot.discord.is_closed:
            await self.check_socket()
            await self.read_data()
            await self.write_data()
            await asyncio.sleep(.1)

    async def check_socket(self):
        rready, wready, err = select.select([self.ircsock], [self.ircsock], [])
        for s in rready:
            if s == self.ircsock:
                self.readready = True
        for s in wready:
            if s == self.ircsock:
                self.writeready = True

    async def write_data(self):
        if not self.writeready:
            return

        if not self.sendbuf:
            return

        i = self.sendbuf.pop(0)
        self.socksend(i)

    async def read_data(self):
        if not self.readready: return

        try:
            ircmsg = self.ircsock.recv(2048)
        except BlockingIOError as e:
            self.readready = False
            return

        msg = b''

        if not ircmsg:
            return

        self.buffer += ircmsg
        if self.length is None:
            if '\n' not in self.decode_irc_string(self.buffer):
                return

            sp = self.decode_irc_string(self.buffer).split('\n')
            i = 0
            lens = len(sp)
            for line in sp:
                self.length = len(line)
                msg += b'\n' + self.buffer[:self.length]
                self.buffer = self.buffer[self.length:]
                self.length = None

                if i + 1 == sp[i+1] != '':
                    return

        for mm in self.decode_irc_string(msg).split('\n'):

            m = mm.strip('\n')

            st2a = m.split(' ')
            tokens = len(st2a)

            if tokens > 1:
                if st2a[0] == "ERROR" and st2a[1] == ":Closing":
                    await self.dc_callback()
                    break

                if st2a[0] == "PING":
                    self.sendbuf.append('PONG %s\n' % (st2a[1].strip(':')))

                if st2a[1] == "001":
                    self.idandjoin()

            if tokens > 3:
                if '#' in st2a[2] and st2a[1] == "PRIVMSG":
                    nick = m.split('!')[0][1:]
                    channel = m.split(' PRIVMSG ')[-1].split(' :')[0]
                    message = m.split(':', 2)[2]
                    m2a = message.split(' ')
                    if nick.lower() not in self.config['irc']['ignore_nicks']:
                        await self.onprivmsg(nick, channel, message)

            if tokens > 2:
                if not self.ischecked and st2a[1] == "513" and st2a[2] == str(botnick):
                    self.sendbuf.append('PONG %s %s\n' % (botnick, st2a[8].strip(':')))
                    self.ischecked = True

                if 'NICK' == st2a[1]:
                    nick = m.split('!')[0][1:]
                    newnick = m.split()[2][1:]
                    nick_message = "[IRC] *** {} changes nickname to {}".format(nick, newnick)
                    await self.irc_both(nick_message)

                if 'JOIN' == st2a[1]:
                    nick = m.split('!')[0][1:]
                    if 'JOIN' in nick or ' ' in nick: return
                    chan = m.split()[2].lower()
                    if ' ' in chan: return
                    if nick == self.botnick: return
                    join_message = "[IRC] *** {} has joined".format(nick)
                    if 'airraidsirens' in chan:
                        await self.bot.isend(self.config['channels']['ars_general'], join_message)
                    elif 'mapping' in chan:
                        await self.bot.isend(self.config['channels']['ars_mapping'], join_message)

                if 'PART' == st2a[1]:
                    nick = m.split('!')[0][1:]
                    if 'PART' in nick or ' ' in nick: return
                    chan = m.split()[2].lower()
                    if ' ' in chan: return
                    part_message = "[IRC] *** {} has left".format(nick)
                    if 'airraidsirens' in chan:
                        await self.bot.isend(self.config['channels']['ars_general'], part_message)
                    elif 'mapping' in chan:
                        await self.bot.isend(self.config['channels']['ars_mapping'], part_message)

                if 'QUIT' == st2a[1]:
                    nick = m.split('!')[0][1:]
                    if nick == self.botnick: return
                    quit_message = "[IRC] *** {} has quit".format(nick)
                    await self.irc_both(quit_message)
