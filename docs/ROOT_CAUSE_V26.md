# Root cause

The canonical prebootstrap implementation was correct but not guaranteed to install before `bot.bot_main` import. That race left the manager singleton constructed yet unwired (`_fsm_initialized=False`), so capital hydration and activation correctly remained blocked. The v26 launcher eliminates the race by installing the import hook before application import.
