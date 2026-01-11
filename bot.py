import os
from dotenv import load_dotenv
import discord
from discord import app_commands
from pymongo import MongoClient

load_dotenv()

# MongoDB 설정
mongo_client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
db = mongo_client["momorice"]
tracked_collection = db["tracked_messages"]

# 봇 설정
intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.dm_messages = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


def is_tracked(message_id: int) -> bool:
    """메시지가 추적 중인지 확인"""
    return tracked_collection.find_one({"message_id": message_id}) is not None


def get_tracker_id(message_id: int) -> int | None:
    """추적 요청자 ID 조회"""
    doc = tracked_collection.find_one({"message_id": message_id})
    return doc["user_id"] if doc else None


def add_tracked(message_id: int, user_id: int, guild_id: int, channel_id: int) -> None:
    """추적 메시지 추가"""
    tracked_collection.insert_one({
        "message_id": message_id,
        "user_id": user_id,
        "guild_id": guild_id,
        "channel_id": channel_id,
    })


def remove_tracked(message_id: int) -> None:
    """추적 메시지 삭제"""
    tracked_collection.delete_one({"message_id": message_id})


def get_user_tracked_count(user_id: int) -> int:
    """사용자가 추적 중인 메시지 수"""
    return tracked_collection.count_documents({"user_id": user_id})


@client.event
async def on_ready():
    await tree.sync()
    print(f"{client.user} 로그인 완료!")


# 메시지 컨텍스트 메뉴 명령어 (메시지 우클릭 -> Apps -> 반응 추적)
@tree.context_menu(name="반응 추적")
async def track_message(interaction: discord.Interaction, message: discord.Message):
    if is_tracked(message.id):
        await interaction.response.send_message("이미 추적 중인 메시지입니다.", ephemeral=True)
        return

    add_tracked(
        message_id=message.id,
        user_id=interaction.user.id,
        guild_id=interaction.guild_id,
        channel_id=message.channel.id,
    )

    await interaction.response.send_message(
        f"메시지 추적을 시작합니다! 누군가 반응을 추가하면 DM으로 알려드릴게요.",
        ephemeral=True
    )


# 메시지 컨텍스트 메뉴 명령어 (메시지 우클릭 -> Apps -> 추적 중지)
@tree.context_menu(name="추적 중지")
async def untrack_message(interaction: discord.Interaction, message: discord.Message):
    tracker_id = get_tracker_id(message.id)

    if tracker_id is None:
        await interaction.response.send_message(
            "이 메시지는 추적 중이 아닙니다.",
            ephemeral=True
        )
        return

    if tracker_id != interaction.user.id:
        await interaction.response.send_message(
            "본인이 추적 중인 메시지만 중지할 수 있습니다.",
            ephemeral=True
        )
        return

    remove_tracked(message.id)
    await interaction.response.send_message(
        "메시지 추적을 중지했습니다.",
        ephemeral=True
    )


# 추적 중인 메시지 목록 확인
@tree.command(name="tracked", description="현재 추적 중인 메시지 목록을 확인합니다")
async def list_tracked(interaction: discord.Interaction):
    count = get_user_tracked_count(interaction.user.id)

    if count == 0:
        await interaction.response.send_message(
            "현재 추적 중인 메시지가 없습니다.",
            ephemeral=True
        )
        return

    await interaction.response.send_message(
        f"추적 중인 메시지: {count}개",
        ephemeral=True
    )


@client.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    # 추적 중인 메시지인지 확인
    tracker_user_id = get_tracker_id(payload.message_id)
    if tracker_user_id is None:
        return

    # 봇 자신의 반응은 무시
    if payload.user_id == client.user.id:
        return

    # 추적 요청자 본인의 반응은 무시
    if payload.user_id == tracker_user_id:
        return

    try:
        # 추적 요청자에게 DM 전송
        tracker_user = await client.fetch_user(tracker_user_id)
        reactor_user = await client.fetch_user(payload.user_id)

        # 채널과 메시지 정보 가져오기
        channel = client.get_channel(payload.channel_id)
        if channel is None:
            channel = await client.fetch_channel(payload.channel_id)

        message_link = f"https://discord.com/channels/{payload.guild_id}/{payload.channel_id}/{payload.message_id}"

        embed = discord.Embed(
            title="새로운 반응이 추가되었습니다!",
            description=f"**{reactor_user.display_name}**님이 반응을 추가했습니다.",
            color=discord.Color.blue()
        )
        embed.add_field(name="반응", value=str(payload.emoji), inline=True)
        embed.add_field(name="채널", value=f"#{channel.name}" if hasattr(channel, 'name') else "알 수 없음", inline=True)
        embed.add_field(name="메시지 링크", value=f"[바로가기]({message_link})", inline=False)

        await tracker_user.send(embed=embed)

    except discord.Forbidden:
        print(f"DM을 보낼 수 없습니다: 사용자 {tracker_user_id}")
    except Exception as e:
        print(f"오류 발생: {e}")


def run_bot():
    token = os.getenv("DISCORD_TOKEN")
    if token is None:
        print("DISCORD_TOKEN 환경변수를 설정해주세요.")
        return
    client.run(token)


if __name__ == "__main__":
    run_bot()
