"""Discord event and interaction handlers — wire discord.py client to Engine."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from .formatters import event_to_button_labels, event_to_embed, event_to_text

if TYPE_CHECKING:
    from openhydra.channels.access import AccessControl
    from openhydra.channels.context import ChannelContext
    from openhydra.events import Event

logger = logging.getLogger(__name__)


class DiscordHandlers:
    """Registers Discord listeners and routes them to Engine operations."""

    def __init__(
        self,
        client: Any,
        ctx: ChannelContext,
        access: AccessControl,
    ) -> None:
        self._client = client
        self._engine = ctx.engine
        self._sessions = ctx.sessions
        self._debouncer = ctx.debouncer
        self._access = access
        # Map workflow_id → (channel_id, thread_id) for threaded replies
        self._threads: dict[str, tuple[int, int]] = {}

    async def _check_access(self, user_id: str, interaction: Any = None) -> bool:
        """Check if user is allowed — delegates to AccessControl."""
        async def notify(msg: str) -> None:
            if interaction:
                await interaction.response.send_message(msg)

        return await self._access.check_and_notify("discord", user_id, notify_fn=notify)

    def register(self) -> None:
        """Register slash command tree, interaction handlers, and subscribe to events."""
        import discord
        from discord import app_commands

        tree = app_commands.CommandTree(self._client)

        @tree.command(name="hydra", description="OpenHydra task management")
        @app_commands.describe(
            action="run|status|approve|reject|pause|resume|cancel",
            argument="Task, workflow ID, or approval ID",
        )
        async def hydra_command(
            interaction: discord.Interaction, action: str, argument: str = "",
        ) -> None:
            await self._handle_command(interaction, action, argument)

        self._tree = tree

        # Button interactions
        @self._client.event
        async def on_interaction(interaction: discord.Interaction):
            if interaction.type == discord.InteractionType.component:
                custom_id = interaction.data.get("custom_id", "")
                await self._handle_button(interaction, custom_id)

        # Subscribe to engine events via EventBus
        self._engine.events.on_all(self.on_engine_event)

    async def sync_commands(self) -> None:
        """Sync slash commands with Discord (call after bot is ready)."""
        await self._tree.sync()

    async def _handle_command(
        self, interaction: Any, action: str, argument: str,
    ) -> None:
        """Route /hydra subcommands to engine operations."""
        user_id = str(interaction.user.id) if hasattr(interaction, "user") else ""
        if not await self._check_access(user_id, interaction=interaction):
            return

        action = action.lower().strip()

        if action == "run":
            if not argument:
                await interaction.response.send_message("Please provide a task description.")
                return

            # Debounce if configured
            text = argument
            if self._debouncer:
                combined = await self._debouncer.debounce(f"discord:{user_id}", text)
                if combined is None:
                    await interaction.response.send_message("Message queued...")
                    return
                text = combined

            await interaction.response.defer()
            workflow_id = await self._engine.submit(text)
            # Track thread for progress updates
            channel_id = interaction.channel_id
            msg = await interaction.followup.send(
                f"Workflow `{workflow_id[:8]}` started: {text}",
                wait=True,
            )
            if hasattr(msg, "id"):
                self._threads[workflow_id] = (channel_id, msg.id)

            # Store in session if available
            if self._sessions:
                from openhydra.channels.session import ChannelSession

                session_key = f"discord:{user_id}"
                session = ChannelSession(
                    session_key=session_key,
                    active_workflow_id=workflow_id,
                    last_channel="discord",
                    last_message_at=datetime.now(timezone.utc),
                    metadata={
                        "channel_id": channel_id,
                        "message_id": msg.id if hasattr(msg, "id") else 0,
                    },
                )
                await self._sessions.upsert(session)

        elif action == "status":
            await self._handle_status(interaction, argument)

        elif action == "approve":
            if not argument:
                await interaction.response.send_message("Please provide an approval ID.")
                return
            await self._engine.approve(argument)
            await interaction.response.send_message(f"Approved `{argument}`")

        elif action == "reject":
            if not argument:
                await interaction.response.send_message("Please provide an approval ID.")
                return
            await self._engine.reject(argument, "Rejected via Discord")
            await interaction.response.send_message(f"Rejected `{argument}`")

        elif action == "pause":
            if not argument:
                await interaction.response.send_message("Please provide a workflow ID.")
                return
            await self._engine.pause(argument)
            await interaction.response.send_message(f"Paused workflow `{argument[:8]}`")

        elif action == "resume":
            if not argument:
                await interaction.response.send_message("Please provide a workflow ID.")
                return
            await self._engine.resume(argument)
            await interaction.response.send_message(f"Resumed workflow `{argument[:8]}`")

        elif action == "cancel":
            if not argument:
                await interaction.response.send_message("Please provide a workflow ID.")
                return
            await self._engine.cancel(argument)
            await interaction.response.send_message(f"Cancelled workflow `{argument[:8]}`")

        else:
            await interaction.response.send_message(
                f"Unknown action: `{action}`. "
                f"Use `run`, `status`, `approve`, `reject`, `pause`, `resume`, or `cancel`.",
            )

    async def _handle_status(self, interaction: Any, argument: str) -> None:
        """Handle /hydra status command."""
        import discord

        await interaction.response.defer()
        if argument:
            wf = await self._engine.get_status(argument)
            embed = discord.Embed(
                title=f"Workflow {wf['id'][:8]}",
                description=f"Status: {wf['status']}",
                color=0x36A64F if wf["status"] == "completed" else 0xDAA038,
            )
            await interaction.followup.send(embed=embed)
        else:
            workflows = await self._engine.list_workflows()
            if not workflows:
                await interaction.followup.send("No workflows found.")
                return
            lines = [
                f"`{w['id'][:8]}` — {w['status']} — {w['input'][:40]}"
                for w in workflows
            ]
            await interaction.followup.send("\n".join(lines))

    async def _handle_button(self, interaction: Any, custom_id: str) -> None:
        """Handle approve/reject/pause/resume/cancel button clicks."""
        if custom_id.startswith("approve:"):
            approval_id = custom_id[len("approve:"):]
            await self._engine.approve(approval_id)
            await interaction.response.send_message(f"Approved `{approval_id}`")
        elif custom_id.startswith("reject:"):
            approval_id = custom_id[len("reject:"):]
            await self._engine.reject(approval_id, "Rejected via Discord")
            await interaction.response.send_message(f"Rejected `{approval_id}`")
        elif custom_id.startswith("pause:"):
            wf_id = custom_id[len("pause:"):]
            await self._engine.pause(wf_id)
            await interaction.response.send_message(f"Paused workflow `{wf_id[:8]}`")
        elif custom_id.startswith("resume:"):
            wf_id = custom_id[len("resume:"):]
            await self._engine.resume(wf_id)
            await interaction.response.send_message(f"Resumed workflow `{wf_id[:8]}`")
        elif custom_id.startswith("cancel:"):
            wf_id = custom_id[len("cancel:"):]
            await self._engine.cancel(wf_id)
            await interaction.response.send_message(f"Cancelled workflow `{wf_id[:8]}`")

    async def on_engine_event(self, event: Event) -> None:
        """Forward engine events to the appropriate Discord thread."""
        wf_id = event.data.get("workflow_id", "")
        thread_info = self._threads.get(wf_id)
        if not thread_info:
            return

        # Cleanup first — always runs even if send fails
        is_terminal = event.type in ("workflow.completed", "workflow.failed", "workflow.cancelled")

        channel_id, message_id = thread_info
        embed_dict = event_to_embed(event)
        text = event_to_text(event)
        buttons = event_to_button_labels(event)

        try:
            channel = self._client.get_channel(channel_id)
            if channel is not None:
                import discord

                embed = discord.Embed.from_dict(embed_dict)
                view = None

                if buttons:
                    view = discord.ui.View()
                    for btn in buttons:
                        style = (
                            discord.ButtonStyle.green
                            if btn["style"] == "green"
                            else discord.ButtonStyle.red
                        )
                        view.add_item(discord.ui.Button(
                            label=btn["label"],
                            custom_id=btn["custom_id"],
                            style=style,
                        ))

                await channel.send(
                    content=text,
                    embed=embed,
                    view=view,
                    reference=discord.MessageReference(
                        message_id=message_id, channel_id=channel_id,
                    ),
                )
        except Exception:
            logger.exception("Failed to send Discord message for event %s", event.type)

        if is_terminal:
            self._threads.pop(wf_id, None)
            if self._sessions:
                await self._sessions.clear_workflow(wf_id)

    async def send_message(self, user_id: str, text: str) -> None:
        """Send a DM to a Discord user."""
        try:
            user = await self._client.fetch_user(int(user_id))
            if user:
                await user.send(text)
        except Exception:
            logger.exception("Failed to send Discord DM to %s", user_id)
