import asyncio

class Random:
    def __init__(self, bot):
        self.bot = bot
        self.config = bot.config
        self.discord = self.bot.discord

    async def on_message(self, message):
        if str(message.author.id) == str(self.discord.user.id):
                return
