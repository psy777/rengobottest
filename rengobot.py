import os
import ast
import time
import asyncio
import sgfengine
import discord
import json
import subprocess
import sgfmill
import importlib
import cairosvg

from datetime import datetime, timedelta
from discord.ext import commands

importlib.reload(sgfengine)

def load_config(file_path):
    try:
        with open(file_path, 'r') as file:
            return json.load(file)
    except FileNotFoundError:
        print(f"Error: The configuration file '{file_path}' was not found.")
    except json.JSONDecodeError:
        print(f"Error: Could not parse JSON in file '{file_path}'. Check its syntax.")
    except Exception as e:
        print(f"An error occurred while reading '{file_path}': {e}")
    return {}

# Function to parse integers or lists of integers
def parse_int_list(value):
    try:
        return list(map(int, value.split(',')))
    except ValueError:
        print(f"Error: Could not convert '{value}' to a list of integers.")
        return []

# Load configuration from the JSON file
config = load_config('config.json')

# Extract and convert configuration values
token = config.get("DISCORD_TOKEN", "")
admins = parse_int_list(config.get("ADMINS", ""))
teachers = parse_int_list(config.get("TEACHERS", ""))
awesome_server_id = config.get("AWESOME_SERVER_ID", 0)
permitted_channel_ids = parse_int_list(config.get("PERMITTED_CHANNEL_IDS", ""))
white_stone = config.get("WHITE_STONE", ":white_circle:")
black_stone = config.get("BLACK_STONE", ":black_circle:")

# Set up the intents
intents = discord.Intents.default()
intents.messages = True
intents.members = True

# Initialize the bot with command prefix and intents
bot = commands.Bot(command_prefix='$', help_command=None, intents=intents)

min_time_player= timedelta(seconds=1) # in random games, min time between same player plays (default days=1)
time_to_skip= timedelta(days=1) # in queue games, how much time to wait for the next move
min_players = 2

format="%Y_%m_%d_%H_%M_%S_%f"

# The state is a list of tuples (channel_id, "queue"/"random", last_players, last_times, [black_queue, white_queue])

@bot.command()
async def help(ctx):
    if ctx.guild.id == awesome_server_id and ctx.channel.id not in permitted_channel_ids: return
    await ctx.send(
            '$help : shows this help\n\n'+

            '$join : join the game in this channel\n'+
            '$leave: leave the game in this channel\n'+
            '$play <move>: play a move. For example, `$play Q16`. Passing is not implemented!\n'+
            '$edit <move>: if you make a mistake in your move, you have 5 minutes to correct it with this command\n\n'+

            '$sgf: get the sgf file of the game\n'+
            '$board: shows the current board\n'+
            '$queue: get the queue of players\n\n'+

            '$newgame <queue/random/teachers> <handicap> <komi>: starts a game in this channel (admin only!)\n'+
            '$resign <B/W>: <B/W> resigns the game in this channel. It returns its sgf file (admin only!)'
            )
    # ctx has guild, message, author, send, and channel (?)

@bot.command()
async def play(ctx, arg):
    if ctx.guild.id == awesome_server_id and ctx.channel.id not in permitted_channel_ids: return
    channel_id= ctx.channel.id
    user = ctx.author
    guild= ctx.guild

    # lowest effort serialization
    with open("state.txt") as f: state = ast.literal_eval(f.read())

    filter_state= [i for i in range(len(state))  if state[i][0] == channel_id] # This is where I should use a fancy next()
    if not filter_state:
        await ctx.send("No active game in this channel!")
        return

    i= filter_state[0]

    if state[i][1] in ["queue", "teachers"] and user.id not in state[i][4][0]+state[i][4][1]:
        await ctx.send("Player hasn't joined yet! Join us with `$join`")
        return

    if state[i][1] == "queue" and (len(state[i][4][0])<min_players or len(state[i][4][1]) <min_players):
        await ctx.send("Waiting for more players to join! Minimum {} per team".format(min_players))
        return

    colour= sgfengine.next_colour(str(channel_id))

    if (state[i][1] == "queue" and user.id!= state[i][4][colour][0]) or (state[i][1]=="teachers" and ((colour==0 and user.id!=state[i][4][0][0]) or (colour==1 and user.id not in state[i][4][1]))):
        await ctx.send("It is not your turn yet!")
        return

    if state[i][1] == "random":
        assert( len(state[i][2]) == len(state[i][3]))

        if len(state[i][2])>0 and state[i][2][-1] == user.id and (state[i][1]!="teachers" or colour=="0"):
            await ctx.send("No two consecutive moves by the same player!")
            # return

        for j in range(len(state[i][2])):
            if (state[i][2][j] == user.id and
                datetime.now() - datetime.strptime(state[i][3][j],format) < min_time_player):
                await ctx.send("At most one move per player per day!")
                return


    if state[i][3] != [] and datetime.now()-datetime.strptime(state[i][3][-1],format)<timedelta(seconds=4):
        return #silent error

    legal_moves=[chr(col+ord('A')-1)+str(row) for col in range(1,21) if col!=9 for row in range(1,20)]
    legal_moves+=[chr(col+ord('a')-1)+str(row) for col in range(1,21) if col!=9 for row in range(1,20)]
    if arg not in legal_moves:
        await ctx.send("I don't understand the move! Please input it in the format `$play Q16`")
        return

    try:
        sgfengine.play_move(str(channel_id), arg, user.display_name)
    except ValueError as e:
        await ctx.send(str(e))
        return

    # move registered, let's do the other things
    state[i][2].append(user.id)
    state[i][3].append(datetime.now().strftime(format))

    if state[i][1] == "queue":
        state[i][4][colour].pop(0)
        state[i][4][colour].append(user.id)

    if state[i][1] == "teachers" and colour==0:
        state[i][4][0].pop(0)
        state[i][4][0].append(user.id)

    file = discord.File(str(ctx.channel.id)+".png")
    if state[i][1]=="queue":
        next_player=(await guild.fetch_member(state[i][4][1-colour][0]))
        await ctx.send(file=file, content="{}'s turn! ⭐".format(next_player.mention))
    elif state[i][1]=="teachers" and colour==1:
        next_player=(await guild.fetch_member(state[i][4][1-colour][0]))
        await ctx.send(file=file, content="{}'s turn! ⭐".format(next_player.mention))
    elif state[i][1]=="teachers" and colour==0:
        await ctx.send("Teachers' turn! ⭐")
        await board(ctx)
    else:
        await board(ctx)

    with open("state.txt", "w") as f: f.write(repr(state))

@bot.command()
async def edit(ctx, arg):
    if ctx.guild.id == awesome_server_id and ctx.channel.id not in permitted_channel_ids:
        return

    channel_id = ctx.channel.id
    user = ctx.author
    guild = ctx.guild

    # Lowest effort serialization
    with open("state.txt") as f:
        state = ast.literal_eval(f.read())

    filter_state = [i for i in range(len(state)) if state[i][0] == channel_id]
    if not filter_state:
        await ctx.send("No active game in this channel!")
        return

    i = filter_state[0]
    colour = sgfengine.next_colour(str(channel_id))

    if len(state[i][2]) == 0 or state[i][2][-1] != user.id or datetime.now() - datetime.strptime(state[i][3][-1], format) > timedelta(minutes=5):
        await ctx.send("You cannot edit this move!")
        return

    legal_moves = [chr(col + ord('A') - 1) + str(row) for col in range(1, 21) if col != 9 for row in range(1, 20)]
    legal_moves += [chr(col + ord('a') - 1) + str(row) for col in range(1, 21) if col != 9 for row in range(1, 20)]
    if arg not in legal_moves:
        await ctx.send("I don't understand the move! Please input it in the format `$play Q16`")
        return

    try:
        sgfengine.play_move(str(channel_id), arg, user.display_name, True)
    except ValueError as e:
        await ctx.send(str(e))
        return

    await board(ctx)

    with open("state.txt", "w") as f:
        f.write(repr(state))

@bot.command()
async def board(ctx):
    if ctx.guild.id == awesome_server_id and ctx.channel.id not in permitted_channel_ids:
        return

    channel_id = ctx.channel.id
    user = ctx.author
    guild = ctx.guild

    with open("state.txt") as f:
        state = ast.literal_eval(f.read())

    filter_state = [i for i in range(len(state)) if state[i][0] == channel_id]
    if not filter_state:
        await ctx.send("No active game in this channel!")
        return

    i = filter_state[0]
    colour = sgfengine.next_colour(str(channel_id))

    # Step 1: Render SVG file
    svg_filename = f"{channel_id}.svg"
    png_filename = f"{channel_id}.png"
    os.system(f"sgf-render --style fancy --label-sides nesw -o {svg_filename} -n last {channel_id}.sgf")

    # Step 2: Convert SVG to PNG
    cairosvg.svg2png(url=svg_filename, write_to=png_filename, dpi=300, output_width=800, output_height=800)

    # Send the PNG file to Discord
    file = discord.File(png_filename)
    if state[i][1] == "queue":
        if len(state[i][4][colour]) > 0:
            next_player = await guild.fetch_member(state[i][4][colour][0])
            await ctx.send(file=file, content=f"{next_player.display_name}'s turn! ⭐")
        else:
            await ctx.send(file=file, content="Waiting for players to join!")
    elif state[i][1] == "teachers":
        if colour == 0:
            next_player = await guild.fetch_member(state[i][4][colour][0])
            await ctx.send(file=file, content=f"{next_player.display_name}'s turn! ⭐")
        else:
            await ctx.send(file=file, content="Teachers' turn! ⭐")
    else:
        await ctx.send(file=file)

@bot.command()
async def join(ctx):
    if ctx.guild.id == awesome_server_id and ctx.channel.id not in permitted_channel_ids: return
    channel_id= ctx.channel.id
    user = ctx.author

    # lowest effort serialization
    with open("state.txt") as f: state = ast.literal_eval(f.read())

    filter_state= [i for i in range(len(state))  if state[i][0] == channel_id]
    if not filter_state:
        await ctx.send("No active game in this channel!")
        return

    i= filter_state[0]

    if user.id in (state[i][4][0]+state[i][4][1]):
        await ctx.send("Player already in this game!")
        return

    if state[i][1] == "random":
        await ctx.send("This game has no queue! No need to join, just `$play` whenever you want :P")
        return

    colour = 0 if len(state[i][4][0])<=len(state[i][4][1]) else 1
    if state[i][1]=="teachers": colour= 0

    state[i][4][colour].append(user.id)

    await ctx.send("{} joined Team {}!".format(user.display_name, ("Black" if colour==0 else "White")))

    with open("state.txt", "w") as f: f.write(repr(state))

@bot.command()
async def leave(ctx):
    if ctx.guild.id == awesome_server_id and ctx.channel.id not in permitted_channel_ids: return
    channel_id= ctx.channel.id
    user = ctx.author

    # lowest effort serialization
    with open("state.txt") as f: state = ast.literal_eval(f.read())

    filter_state= [i for i in range(len(state))  if state[i][0] == channel_id]
    if not filter_state:
        await ctx.send("No active game in this channel!")
        return

    i= filter_state[0]

    if user.id not in (state[i][4][0]+state[i][4][1]):
        await ctx.send("Player not in this game!")
        return

    if state[i][1] == "random":
        await ctx.send("This game has no queue! No need to leave!")
        return

    colour = 0 if (user.id in state[i][4][0]) else 1
    state[i][4][colour].remove(user.id)

    await ctx.send("{} left :(".format(user.display_name))

    with open("state.txt", "w") as f: f.write(repr(state))

@bot.command()
async def queue(ctx):
    if ctx.guild.id == awesome_server_id and ctx.channel.id not in permitted_channel_ids: return
    channel_id= ctx.channel.id
    channel= bot.get_channel(channel_id) # thonk the order
    guild = channel.guild

    # lowest effort serialization
    with open("state.txt") as f: state = ast.literal_eval(f.read())

    filter_state= [i for i in range(len(state))  if state[i][0] == channel_id]
    if not filter_state:
        await ctx.send("No active game in this channel!")
        return

    i= filter_state[0]
    colour= sgfengine.next_colour(str(channel_id))

    if state[i][1] == "random":
        await ctx.send("This game has no queue! No need to join, just `$play` whenever you want :P")
        return

    if state[i][1] =="teachers":
        output="Player list for Team Black: "+black_stone+"\n"
        for j, player_id in enumerate(state[i][4][0]):
            player_name=(await guild.fetch_member(player_id)).display_name
            output+=str(j+1).rjust(3)+". "+ player_name+"\n"
        await ctx.send(output)
        return

    output= "Player list:\n"
    if state[i][4][0]==[] and state[i][4][1] == []:
        output+="Nobody yet! Join us with `$join`"
        await ctx.send(output)
        return

    if state[i][4][0] == []:
        for j, player_id in enumerate(state[i][4][1]):
            player_name=(await guild.fetch_member(player_id)).display_name
            output+=white_stone+str(j+1).rjust(3)+". "+ player_name+"\n"
        output+="\n Team Black needs more members!"
        await ctx.send(output)
        return

    if state[i][4][1] == []:
        for j, player_id in enumerate(state[i][4][0]):
            player_name=(await guild.fetch_member(player_id)).display_name
            output+=black_stone+str(j+1).rjust(3)+". "+ player_name+"\n"
        output+="\n Team White needs more members!"
        await ctx.send(output)
        return

    # Which team has more members? Or in case of a tie, which team goes first?
    if len(state[i][4][colour]) > len(state[i][4][1-colour]):
        last_player = state[i][4][colour][-1]
    else: last_player= state[i][4][1-colour][-1]

    j=1
    pointers=[0,0]
    while(True):
        #print(channel_id, j, pointers, colour, state[i][0], state[i][4])
        output+= white_stone if ((colour+1) % 2 ==0)  else black_stone
        output+= str(j).rjust(3)+". "

        player_name= (await guild.fetch_member(state[i][4][colour][pointers[colour]])).display_name
        output+= player_name+"\n"

        if state[i][4][colour][pointers[colour]] == last_player: break

        pointers[colour] = (pointers[colour]+1) % len(state[i][4][colour])
        colour=1-colour

        j+=1

    if len(state[i][4][0])<min_players:
        output+="\n Team Black needs more members!"

    if len(state[i][4][1])<min_players:
        output+="\n Team White needs more members!"

    await ctx.send(output)

@bot.command()
async def sgf(ctx):
    if ctx.guild.id == awesome_server_id and ctx.channel.id not in permitted_channel_ids: return
    file = discord.File(str(ctx.channel.id)+".sgf")
    await ctx.send(file=file)

@bot.command()
async def newgame(ctx, *args):
    if ctx.guild.id == awesome_server_id and ctx.channel.id not in permitted_channel_ids: return
    channel_id= ctx.channel.id
    user = ctx.author

    if user.id not in admins:
        await ctx.send("You don't have permission to start a new game.")
        return

    if len(args) == 0:
        await ctx.send("No gave type given! Please use `$newgame <random/queue/teachers>`")

    gametype = args[0].lower()

    if gametype not in ["queue", "random", "teachers"]:
        await ctx.send("Unrecognized game type! Please use `$newgame <queue/random/teachers>`")
        return

    # Set default values for handicap and komi, and override if provided
    try:
        handicap = int(args[1]) if len(args) > 1 else 0
        komi = float(args[2]) if len(args) > 2 else 6.5
    except ValueError:
        await ctx.send("Invalid values for handicap or komi. Please provide valid numbers.")
        return

    # lowest effort serialization
    try:
        with open("state.txt") as f: 
            state = ast.literal_eval(f.read())
    except FileNotFoundError:
        state = []
    except Exception as e:
        await ctx.send (f"An error occurred while reading the game state: {e}")
        return

    if ctx.channel.id in [ ch for (ch,_,_,_,_) in state]:
        await ctx.send("A game is already active in this channel!")
        return

    sgfengine.new_game(str(ctx.channel.id), handicap, komi)

    if gametype== "teachers":
        state.append((ctx.channel.id, gametype, [], [], [[],teachers]))
    else:
        state.append((ctx.channel.id, gametype, [], [], [[],[]]))
    
    if gametype in ["queue", "teachers"]:
        await ctx.send("A new game has started! Join with `$join`")
    else:
        await ctx.send("A new game has started! Play with `$play <move>`")

    with open("state.txt", "w") as f: f.write(repr(state))
    await board(ctx)

@bot.command() # working rn, Todo: make this command delete the proper files from somewhere at the end of the game
async def resign(ctx, *args):
    if ctx.guild.id == awesome_server_id and ctx.channel.id not in permitted_channel_ids: return
    channel_id= ctx.channel.id
    user = ctx.author

    if user.id not in admins:
        await ctx.send("You don't have permissions for this!")
        return

        # Handle missing or incorrect arguments
    if len(args) == 0:
        await ctx.send("No argument given! Please choose `B` or `W` to resign as Black/White.")
        return

    arg = args[0].upper()  # Convert the argument to uppercase for a case-insensitive check

    if arg not in ["W", "B"]:
        await ctx.send("Unrecognized color! Please choose `B` or `W` to resign as Black/White.")
        return

    with open("state.txt") as f: state = ast.literal_eval(f.read())

    now=datetime.now()
    file_name= "rengo_"+now.strftime("%Y_%m_%d_%H_%M_%S_")+ctx.channel.name+".sgf" #remove the hour minute and second later

    sgfengine.resign(str(channel_id), arg, file_name)

    file = discord.File(file_name)
    await ctx.send(file=file, content=("Black" if arg=="W" else "White")+" wins!")

    state = [s for s in state if s[0]!=channel_id]

    with open("state.txt", "w") as f: f.write(repr(state))

async def background_task():
    await bot.wait_until_ready()
    print("bot ready!")

    guild=discord.utils.get(bot.guilds, name="Awesome Baduk")
    game=discord.Game("multiplayer Baduk! $help for command list")
    await bot.change_presence(status=discord.Status.online, activity=game)

    while not bot.is_closed():
        try:
            # lowest effort serialization
            with open("state.txt") as f: state = ast.literal_eval(f.read())
            #print(state)

            #TODO find who has to move, skip players accordingly, notify if any has to move
            for i in range(len(state)):
                if state[i][3] == [] or state[i][1]=="random": continue

                channel_id= state[i][0]
                channel= bot.get_channel(channel_id)

                colour = sgfengine.next_colour(str(channel_id))
                if state[i][1]=="teachers" and colour=="1": continue #Ask the teachers if they want a ping

                last_time= datetime.strptime(state[i][3][-1],format)
                time_left= last_time + time_to_skip-datetime.now()

                if time_left < time_to_skip/3.0 and time_left > time_to_skip/3.0-timedelta(seconds=10): # Probably remove? Depends on how passive aggressive it is
                    next_user = await guild.fetch_member(state[i][4][colour][0])
                    await channel.send("{}'s turn! Time is running up!".format(next_user.mention))#, time_left.total_seconds()/3600) )
                if time_left < timedelta():
                    state[i][3][-1]= datetime.strftime(datetime.now(),format)
                    state[i][2][-1]= None
                    user_id= state[i][4][colour][0]
                    state[i][4][colour].pop(0)
                    state[i][4][colour].append(user_id)
                    next_player=(await guild.fetch_member(state[i][4][colour][0]))
                    await channel.send(content="{}'s turn! ⭐".format(next_player.mention))

            with open("state.txt", "w") as f: f.write(repr(state))
            await asyncio.sleep(10)

        except ConnectionResetError:
            print("Connection error")

bot.loop.create_task(background_task())
bot.run(token)
