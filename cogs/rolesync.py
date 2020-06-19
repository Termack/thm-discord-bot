import asyncio
import json
import time

import aiohttp
import discord
from discord import guild
from discord.channel import DMChannel
from discord.ext import commands
from discord.utils import get

import libs.config as config
import libs.database as database
from libs.utils import api_fetch, has_role, add_role

### Hello, this is Horshark. 
### Before you all @ me, I know. This is disgusting code.
### The update() function should be cleaner.
### The code in verify and the autoupdater can be factorized into the update() function.
### If you are reading this, there probably is an issue about this.
### Sorry for the new pair of glasses you will need.
### Have a good day.
###
### PS: It is planned to eventually rework this.
### PS 2: You can find me on Discord and I'll try to help.


####################
# Config variables #
####################

c_sleeptime = config.get_config("sleep_time")["roles_update"]
c_api_token = config.get_config("url")["api"]["token"]


#####################
# Strings variables #
#####################

s_verify = config.get_string("verify")
s_verify_del = config.get_string("verify_delete")


###################
# Other variables #
###################

id_guild = config.get_config("server")

roles = config.get_config("roles")
id_admin = roles["admin"]
id_mod = roles["mod"]
id_ranks = roles["ranks"]
id_sub = roles["sub"]
id_contrib = roles["contrib"]
id_verified = roles["verified"]

# DB
db = database.connect_to_db()


#############
# Functions #
#############

# Role managment.
async def remove_rank_roles(member):
    """Remove the member's rank/level roles."""

    for rId in id_ranks:
        if has_role(member, rId):
            await member.remove_roles(get(member.guild.roles, id=rId))

async def remove_sub_role(member):
    """Removes the member's sub role."""

    await member.remove_roles(get(member.guild.roles, id=id_sub))

async def remove_contrib_role(member):
    """Remove the user's contrib role."""

    await member.remove_roles(get(member.guild.roles, id=id_contrib))

async def remove_verified_role(member):
    """Remove the user's verified role."""

    await member.remove_roles(get(member.guild.roles, id=id_verified))


# Update a member's roles.
async def update(member, dm, data, skipUpdatedMessage = False):
    """Updates the user's roles."""

    cmdResult = ""

    level = data["level"] - 1
    sub = data["subscribed"]

    # Special case: Contributors.
    if level == 997:
        if not has_role(member, id_contrib):
            await remove_rank_roles(member)
            await add_role(member, id_contrib)
            cmdResult += s_verify["contrib_add"] + "\n"
        else:
            cmdResult += s_verify["level_up-to-date"] + "\n"

    if level != 997 and has_role(member, id_contrib):
        await remove_contrib_role(member)
        cmdResult += s_verify["contrib_remove"] + "\n"

    # Normal ranks.
    if level < len(id_ranks):
        if not has_role(member, id_ranks[level]):
            await remove_rank_roles(member)
            await add_role(member, id_ranks[level])

            cmdResult += s_verify["level_updated"] + "\n"
        elif not skipUpdatedMessage:
                cmdResult += s_verify["level_up-to-date"] + "\n"

    # Checks for the users' sub status.
    if sub == 0:
        if has_role(member, id_sub):
            await remove_sub_role(member)
            cmdResult += s_verify["sub_remove"] + "\n"
    else:
        if not has_role(member, id_sub):
            await add_role(member, id_sub)
            cmdResult += s_verify["sub_added"] + "\n"

    # Checks if the users has the verified role.
    if not has_role(member, id_verified):
        await add_role(member, id_verified)
        cmdResult += s_verify["verified_added"] + "\n"

    if cmdResult != "":
        await dm.send(cmdResult)


############
# COG Body #
############

class RoleSync(commands.Cog, name="Verifying/Role Assigning Commands"):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(description=s_verify["help_desc"], usage="{token}")
    async def verify(self, ctx, user_token=None):

        # If not DM, clear the message so that the token isn't kept publicly.
        if not isinstance(ctx.channel, DMChannel):
            await ctx.message.delete()

            msg = await ctx.send(s_verify["error_not_dm"])
            time.sleep(15)
            await msg.delete()

            return

        # If no token sends message...
        if user_token == None:
            await ctx.send(s_verify["usage"])
            return
        
        # Otherwise, keeps going:
        else:
            cmdResult = ""

            data = await api_fetch(c_api_token, user_token)
            success = data["success"]

            # If the token isn't valid.
            if success == False:
                cmdResult = s_verify["token_not_found"]
                await ctx.send(cmdResult)
            else:
                ### Retrieves needed variables and updates DB if needed. ###

                server = self.bot.get_guild(id_guild)

                # If server ID is wrong.
                if server == None:
                    await ctx.send(s_verify["error"] + "ERROR: Server not found.")
                    return
                

                user = ctx.message.author
                member = server.get_member(user.id)

                # If user isn't a member.
                if member == None:
                    database.remove_user_by_discord_uid(ctx.author.id)
                    await ctx.send(s_verify["not_a_member"])
                    return


                dm_channel = await member.create_dm()

                result = database.get_user_by_thm_token(db, user_token)

                # If user is not in DB; add him.
                if len(result) == 0:
                    database.add_user(db, member.id, user_token)

                ### Updates roles for the user. ###
                await update(member, dm_channel, data)

    @commands.command(name="tokenremove", description=s_verify_del["help_desc"] + " (Admin, Mod)", usage="{@user}", hidden=True)
    async def remove_token(self, ctx, member: discord.Member):

        if has_role(ctx.author, id_admin) or has_role(ctx.author, id_mod):
            # Removes the user from the DB.
            database.remove_user_by_discord_uid(db, member.id)
            msg = s_verify_del["done"].format(member.id)
            
            # Removes the user's roles (verified, sub, contrib, rank..)
            await remove_verified_role(member)
            await remove_sub_role(member)
            await remove_rank_roles(member)
            await remove_contrib_role(member)

            await ctx.send(msg)

    # The function that when called, update every user in the DB.
    async def auto_updater(self):
        """Function that runs constantly to ensure the roles are automaticallyupdated.."""

        ### Retrieves needed variables and updates DB if needed. ###
        server = self.bot.get_guild(id_guild)

        # If server ID is wrong.
        if server == None:
            print(s_verify["error"] + "ERROR: Server not found. (auto updater)")
            return
            
        while True:
            # Logging.
            print("\n---- Updating roles:")

            # We retrieve all users from DB.
            users = database.get_user_all(db)

            for user in users:
                # User's Discord UID and THM token.
                user_dUID = user[0]
                user_thm = user[1]

                # We fetch the user.
                user_member = await server.fetch_member(user_dUID)

                # Logging.
                user_thm_censored = user_thm[:3] + '*'*18 + user_thm[-3:]
                print("\t" + user_member.name + " | " + user_dUID + ", " + user_thm_censored)

                # Getting his data.
                data = await api_fetch(c_api_token, user_thm)

                # Getting the DM channel and calling update function.
                dm_channel = await user_member.create_dm()
                await update(user_member, dm_channel, data, True)
                
            print("-- Role updating finished.\n")

            await asyncio.sleep(c_sleeptime)

    # Starts the auto update.
    @commands.Cog.listener()
    async def on_ready(self):
        await self.auto_updater()

def setup(bot):
    bot.add_cog(RoleSync(bot))
