#!/usr/bin/env python3.5
import asyncio
import configparser
import discord
import traceback
import yaml

from dcmanage import DCManager
from irc import IRCManager
from forums import Forum
from toys import Random
from wiki import Wiki

class Bot:
    def __init__(self):
        self.discord = discord.Client()
        self.config = None
        self.check_config()
        self.forumdb = Forum(self)
        self.wikidb = Wiki(self)
        self.random = Random(self)
        self.dcmanager = DCManager(self)
        self.ircmanager = IRCManager(self)
        # Discord events
        self.discord.event(self.on_ready)
        self.discord.event(self.on_message)
        self.discord.event(self.on_member_join)

    async def on_ready(self):
        print('Logged in as {} ({})'.format(self.discord.user.name, self.discord.user.id))
        print('------')

    async def on_message(self, message):
        await self.dcmanager.on_message(message)
        await self.random.on_message(message)
        asyncio.ensure_future(self.ircmanager.on_message(message))

    async def on_member_join(self, member):
        server = member.server
        fmt = 'Welcome {0.mention} to {1.name}! Here is a quick guide on getting started https://goo.gl/QhfUkQ'
        await self.isend(self.config['channels']['ars_general'], fmt.format(member, server))

    def check_config(self):
        try:
            self.config = yaml.load(open('config.yml', 'r'))
        except yaml.YAMLError:
            self.alert_error(traceback.format_exc())

        if 'discord' not in self.config:
            print("You must supply a valid config file.")
            exit()

    def get_channel(self, name):
        t = str(self.config['channels'][name])
        return self.discord.get_channel(t)

    async def isend(self, cid, message):
        if not cid:
            self.alert_error("No channel ID specified.")

        channel = self.discord.get_channel(cid)

        if channel is None:
            await self.alert_error("isend: Could not find channel! cid = {}, message = {}".format(cid, message))
            return

        try:
            await self.discord.send_message(channel, message)
        except discord.errors.InvalidArgument as ex:
            print("Error sending via isend: {}".format(ex))

    async def alert_debug(self, e):
        if not self.discord.is_closed:
            channel = self.get_channel('ars_debug')
            try:
                await self.discord.send_message(channel, "DEBUG: {}".format(e))
            except discord.errors.InvalidArgument as ex:
                print("Error sending via alert_debug: {}".format(ex))
        print("DEBUG: {}".format(e))

    async def alert_error(self, e):
        if not self.discord.is_closed:
            channel = self.get_channel('ars_debug')
            try:
                await self.discord.send_message(channel, "ERROR: {}".format(e))
            except discord.errors.InvalidArgument as ex:
                print("Error sending via alert_error: {}".format(ex))
        print("An error has occured: {}".format(e))

    async def debug_notify(self, e):
        if not self.discord.is_closed:
            channel = self.get_channel('ars_debug')
            try:
                await self.discord.send_message(channel, "DEBUG: {}".format(e))
            except discord.errors.InvalidArgument as ex:
                print("Error sending via debug_notify: {}".format(ex))

def main():
    bot = Bot()
    key = bot.config['discord']['key']

    try:
        bot.discord.loop.create_task(bot.forumdb.check())
        bot.discord.loop.create_task(bot.wikidb.check())
        bot.discord.loop.create_task(bot.ircmanager.loop())
        bot.discord.loop.create_task(bot.dcmanager.loop())
        bot.discord.run(key)
    except discord.errors.LoginFailure:
        print("Invalid token specified: %s" % (key))
        exit()
    except TypeError:
        asyncio.ensure_future(bot.alert_error(traceback.format_exc()))
    except NameError:
        asyncio.ensure_future(bot.alert_error(traceback.format_exc()))

if __name__ == "__main__":
    main()
