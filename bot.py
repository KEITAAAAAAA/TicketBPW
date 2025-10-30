import discord
from discord.ext import commands
from discord.ui import View, Button, Select, Modal, TextInput
import asyncio
from dotenv import load_dotenv

load_dotenv()

# === CONFIG ===
SUPPORT_ROLE_IDS = [1433258422564028560, 1433258479241662514]
CATEGORY_ACHAT_ID = 1433267521817018409
CATEGORY_VENTE_ID = 1433267681875988521
CATEGORY_SUPPORT_ID = 1433267722313273427
TRANSACTION_LOG_CHANNEL_ID = 1433253388023369870
NEW_MEMBER_ROLE_ID = 1433258613601861724
TRANSACTION_DONE_ROLE_ID = 1433258555020017674
LOGS_BOT_CHANNEL_ID = 1433253764491640863
STAFF_ROLE_ID = 1433258479241662514  # rôle staff à mentionner dans les logs
PAYPAL_EMAIL_ACHAT = "lch.keita@gmail.com"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- DICTIONNAIRE POUR L'ÉTAT DES TICKETS ---
ticket_states = {}  # {channel_id: {"claimed_by": user_id, "type": "buy"/"sell", "amount": float, "completed": False, "user": Member}}

# --- ASSIGN ROLE AUTOMATIQUE AUX NOUVEAUX MEMBRES ---
@bot.event
async def on_member_join(member):
    role = member.guild.get_role(NEW_MEMBER_ROLE_ID)
    if role:
        await member.add_roles(role)

# --- FONCTION POUR LOG TICKET ---
async def log_ticket_creation(ticket_type, user, channel, amount=None):
    log_channel = bot.get_channel(LOGS_BOT_CHANNEL_ID)
    staff_mention = f"<@&{STAFF_ROLE_ID}>"
    if log_channel:
        embed = discord.Embed(
            title=f"📝 New Ticket Created / Nouveau Ticket",
            description=f"Type: {ticket_type.capitalize()}\nUser: {user.mention}\nChannel: {channel.mention}",
            color=discord.Color.orange()
        )
        if amount:
            embed.add_field(name="Amount / Montant", value=f"{amount} coins", inline=False)
        await log_channel.send(embed=embed)
        await log_channel.send(staff_mention)

# --- MODAL POUR SAISIR LE MONTANT ---
class AmountModal(Modal):
    def __init__(self, ticket_type, user):
        super().__init__(title=f"{'Buy / Achat' if ticket_type=='buy' else 'Sell / Vente'} Coins")
        self.ticket_type = ticket_type
        self.user = user
        self.amount_input = TextInput(label="Amount / Montant", placeholder="Ex: 10 coins", required=True)
        self.add_item(self.amount_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            coins = float(self.amount_input.value)
        except ValueError:
            await interaction.response.send_message("❌ Enter a valid number / Entrez un nombre valide.", ephemeral=True)
            return

        guild = interaction.guild
        category_id = CATEGORY_ACHAT_ID if self.ticket_type=="buy" else CATEGORY_VENTE_ID
        category = discord.utils.get(guild.categories, id=category_id)

        overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}
        overwrites[self.user] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
        for role_id in SUPPORT_ROLE_IDS:
            role = guild.get_role(role_id)
            overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        ticket_channel = await guild.create_text_channel(
            name=f"{self.ticket_type}-{self.user.name}",
            category=category,
            overwrites=overwrites
        )

        ticket_states[ticket_channel.id] = {"claimed_by": None, "type": self.ticket_type, "amount": coins, "completed": False, "user": self.user}

        embed = discord.Embed(
            title=f"🎫 Ticket Created / Ticket Créé",
            description=f"{self.user.mention}, staff will claim and confirm / Le staff va prendre et confirmer le ticket.\n\nAmount / Montant: {coins} coins",
            color=discord.Color.green() if self.ticket_type=="buy" else discord.Color.blurple()
        )

        view = ClaimConfirmView(ticket_type=self.ticket_type, user=self.user)
        await ticket_channel.send(embed=embed, view=view)
        await interaction.response.send_message(f"✅ Ticket created / Ticket créé : {ticket_channel.mention}", ephemeral=True)
        # --- LOG TICKET ---
        await log_ticket_creation(self.ticket_type, self.user, ticket_channel, amount=coins)

# --- MODAL POUR CANDIDATURE STAFF ---
class StaffApplicationModal(Modal):
    def __init__(self, user):
        super().__init__(title="Staff Application / Candidature Staff")
        self.user = user
        self.age = TextInput(label="Age / Âge", placeholder="Your age / Votre âge", required=True)
        self.motivation = TextInput(label="Why become staff? / Pourquoi devenir staff ?", style=discord.TextStyle.paragraph, placeholder="Explain your motivation / Expliquez votre motivation", required=True)
        self.experience = TextInput(label="Experience / Expérience", style=discord.TextStyle.paragraph, placeholder="Previous experience or skills / Expérience ou compétences", required=True)
        self.availability = TextInput(label="Availability / Disponibilité", placeholder="Days/hours you can work / Jours/heures disponibles", required=True)
        self.add_item(self.age)
        self.add_item(self.motivation)
        self.add_item(self.experience)
        self.add_item(self.availability)

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        log_channel = discord.utils.get(guild.text_channels, name="staff-applications")
        if not log_channel:
            log_channel = await guild.create_text_channel("staff-applications", overwrites={guild.default_role: discord.PermissionOverwrite(view_channel=False)})

        embed = discord.Embed(
            title=f"🛡️ New Staff Application / Nouvelle candidature staff",
            description=f"User: {self.user.mention}\nAge: {self.age.value}\nMotivation: {self.motivation.value}\nExperience: {self.experience.value}\nAvailability: {self.availability.value}",
            color=discord.Color.gold()
        )
        await log_channel.send(embed=embed)
        await interaction.response.send_message("✅ Your staff application has been submitted / Votre candidature a été envoyée !", ephemeral=True)

# --- VIEW CLAIM + CONFIRM + CLOSE ---
class ClaimConfirmView(View):
    def __init__(self, ticket_type, user):
        super().__init__(timeout=None)
        self.ticket_type = ticket_type
        self.user = user
        self.claimed = False
        self.claimed_by = None

    @discord.ui.button(label="🖐 Claim / Prendre", style=discord.ButtonStyle.primary)
    async def claim_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.claimed:
            await interaction.response.send_message("❌ This ticket is already claimed / Ce ticket est déjà pris.", ephemeral=True)
            return
        if not any(role.id in SUPPORT_ROLE_IDS for role in interaction.user.roles):
            await interaction.response.send_message("❌ Only staff can claim / Seul le staff peut prendre ce ticket", ephemeral=True)
            return
        self.claimed = True
        self.claimed_by = interaction.user.id
        ticket_states[interaction.channel.id]["claimed_by"] = interaction.user.id
        await interaction.channel.edit(name=f"{interaction.channel.name}-claimed-{interaction.user.name}")
        for item in self.children:
            if item.label.startswith("✅ Confirm"):
                item.disabled = False
        await interaction.response.send_message(f"✅ Ticket claimed by {interaction.user.mention}", ephemeral=True)
        await interaction.message.edit(view=self)

    @discord.ui.button(label="✅ Confirm / Confirmer", style=discord.ButtonStyle.green, disabled=True)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.claimed or self.claimed_by != interaction.user.id:
            await interaction.response.send_message("❌ You must claim first / Vous devez prendre le ticket d'abord", ephemeral=True)
            return
        await interaction.response.send_message("✅ Ticket confirmed. Staff can now use !buy or !sell / Ticket confirmé. Staff peut maintenant utiliser !buy ou !sell", ephemeral=True)

    @discord.ui.button(label="🔒 Close Ticket / Fermer", style=discord.ButtonStyle.red)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("⏳ Ticket will close / Ticket sera fermé...", ephemeral=True)
        await asyncio.sleep(3)
        await interaction.channel.delete()

# --- COMMANDES !buy ET !sell ---
@bot.command()
@commands.has_any_role(*SUPPORT_ROLE_IDS)
async def buy(ctx):
    channel = ctx.channel
    state = ticket_states.get(channel.id)
    if not state or state["claimed_by"] != ctx.author.id or state["type"] != "buy":
        await ctx.send("❌ You must claim a buy ticket first / Vous devez prendre un ticket achat.", delete_after=10)
        return
    member = state["user"]
    coins = state["amount"]

    embed = discord.Embed(
        title="💰 Buy Steps / Étapes Achat",
        description=(
            f"User: {member.mention}\n"
            f"Amount: {coins} coins (~{coins*1:.2f} €)\n\n"
            "1️⃣ Send the amount to PayPal\n"
            "2️⃣ Notify staff with screenshot\n"
            "3️⃣ Send your BPW username\n"
            "4️⃣ Staff will send the coins"
        ),
        color=discord.Color.green()
    )

    view = View()
    btn_finalize = Button(label="✅ Transaction Completed / Transaction terminée", style=discord.ButtonStyle.green)
    async def finalize_callback(interaction: discord.Interaction):
        if not any(role.id == STAFF_ROLE_ID for role in interaction.user.roles):
            await interaction.response.send_message("❌ Only staff can finalize / Seul le staff peut terminer", ephemeral=True)
            return
        await interaction.response.send_message("✅ Transaction logged & ticket will close / Transaction enregistrée et ticket fermé.", ephemeral=True)
        log_channel = bot.get_channel(TRANSACTION_LOG_CHANNEL_ID)
        await log_channel.send(f"📥 Buy completed / Achat terminé: {member.mention} - {coins} coins - Staff: {ctx.author.mention}")
        ticket_states[channel.id]["completed"] = True
        # --- Ajouter rôle transaction done ---
        role_done = ctx.guild.get_role(TRANSACTION_DONE_ROLE_ID)
        if role_done:
            await member.add_roles(role_done)
        await asyncio.sleep(3)
        await channel.delete()
    btn_finalize.callback = finalize_callback
    view.add_item(btn_finalize)
    await channel.send(embed=embed, view=view)

@bot.command()
@commands.has_any_role(*SUPPORT_ROLE_IDS)
async def sell(ctx):
    channel = ctx.channel
    state = ticket_states.get(channel.id)
    if not state or state["claimed_by"] != ctx.author.id or state["type"] != "sell":
        await ctx.send("❌ You must claim a sell ticket first / Vous devez prendre un ticket vente.", delete_after=10)
        return
    member = state["user"]
    coins = state["amount"]

    embed = discord.Embed(
        title="💸 Sell Steps / Étapes Vente",
        description=(
            f"User: {member.mention}\n"
            f"Amount: {coins} coins (~{coins*0.9:.2f} €)\n\n"
            "1️⃣ Staff gives BPW username\n"
            "2️⃣ User sends the coins\n"
            "3️⃣ Staff confirms receipt\n"
            "4️⃣ Staff requests user's PayPal\n"
            "5️⃣ Staff sends money on PayPal\n"
            "6️⃣ User confirms receipt"
        ),
        color=discord.Color.blurple()
    )

    view = View()
    btn_finalize = Button(label="✅ Transaction Completed / Transaction terminée", style=discord.ButtonStyle.green)
    async def finalize_callback(interaction: discord.Interaction):
        if not any(role.id == STAFF_ROLE_ID for role in interaction.user.roles):
            await interaction.response.send_message("❌ Only staff can finalize / Seul le staff peut terminer", ephemeral=True)
            return
        await interaction.response.send_message("✅ Transaction logged & ticket will close / Transaction enregistrée et ticket fermé.", ephemeral=True)
        log_channel = bot.get_channel(TRANSACTION_LOG_CHANNEL_ID)
        await log_channel.send(f"📤 Sell completed / Vente terminée: {member.mention} - {coins} coins - Staff: {ctx.author.mention}")
        ticket_states[channel.id]["completed"] = True
        # --- Ajouter rôle transaction done ---
        role_done = ctx.guild.get_role(TRANSACTION_DONE_ROLE_ID)
        if role_done:
            await member.add_roles(role_done)
        await asyncio.sleep(3)
        await channel.delete()
    btn_finalize.callback = finalize_callback
    view.add_item(btn_finalize)
    await channel.send(embed=embed, view=view)

# --- CREATE PANEL ---
@bot.command()
@commands.has_permissions(administrator=True)
async def createpanel(ctx):
    embed = discord.Embed(
        title="🎟️ Ticket Center / Centre de Tickets",
        description=(
            "Welcome to the ticket system! / Bienvenue sur le système de tickets\n\n"
            "💰 Buy coins / Acheter coins – 1 coin = 1 €\n"
            "💸 Sell coins / Vendre coins – 1 coin = 0,90 €\n"
            "❓ Support / Questions – For any help / Pour toute aide\n"
            "🛡️ Become Staff / Devenir Staff – Apply to become staff / Postulez pour devenir staff\n\n"
            "Choose the ticket type in the menu below / Choisissez le type de ticket ci-dessous 👇"
        ),
        color=discord.Color.blue()
    )
    view = TicketSelectView()
    await ctx.send(embed=embed, view=view)
    await ctx.message.delete()

# --- MENU TICKET ---
class TicketSelectView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketSelectMenu())

class TicketSelectMenu(Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="💰 Buy Coins / Acheter", description="Create a ticket to buy coins / Créer un ticket pour acheter des coins", value="buy"),
            discord.SelectOption(label="💸 Sell Coins / Vendre", description="Create a ticket to sell coins / Créer un ticket pour vendre des coins", value="sell"),
            discord.SelectOption(label="❓ Support / Aide", description="Create a support ticket / Créer un ticket support", value="support"),
            discord.SelectOption(label="🛡️ Become Staff / Devenir Staff", description="Apply to become staff / Postuler pour devenir staff", value="staff"),
        ]
        super().__init__(placeholder="📩 Choose ticket / Choisir ticket", options=options, custom_id="ticket_select")

    async def callback(self, interaction: discord.Interaction):
        user = interaction.user
        guild = interaction.guild
        choice = self.values[0]

        if choice in ["buy", "sell"]:
            modal = AmountModal(ticket_type=choice, user=user)
            await interaction.response.send_modal(modal)
        elif choice == "staff":
            modal = StaffApplicationModal(user=user)
            await interaction.response.send_modal(modal)
        else:
            category = discord.utils.get(guild.categories, id=CATEGORY_SUPPORT_ID)
            ticket_channel = await guild.create_text_channel(
                name=f"support-{user.name}",
                category=category,
                overwrites={guild.default_role: discord.PermissionOverwrite(view_channel=False), user: discord.PermissionOverwrite(view_channel=True, send_messages=True)}
            )
            embed = discord.Embed(
                title="❓ Support Ticket / Ticket Support",
                description=f"{user.mention}, describe your issue here / Décrivez votre problème ici.",
                color=discord.Color.orange()
            )
            view = ClaimConfirmView(ticket_type="support", user=user)
            await ticket_channel.send(embed=embed, view=view)
            await interaction.response.send_message(f"✅ Support ticket created / Ticket support créé : {ticket_channel.mention}", ephemeral=True)
            await log_ticket_creation("support", user, ticket_channel)

@bot.event
async def on_ready():
    print(f"✅ Bot connected / Connecté en tant que {bot.user}")

import os
bot.run(os.getenv("DISCORD_TOKEN"))