"""Utility condivise per barre di avanzamento NiceGUI (0..1 e percentuale etichetta)."""

import asyncio


def job_progress_fraction(completed: int, total: int) -> float:
    """Quota 0..1 per ui.linear_progress (valore proporzionale, non percentuale grezza)."""
    if total <= 0:
        return 0.0
    return min(1.0, max(0.0, float(completed) / float(total)))


def job_progress_percent(completed: int, total: int, *, decimals: int = 2) -> float:
    """Percentuale 0..100 per etichette."""
    if total <= 0:
        return 0.0
    bounded = min(max(int(completed), 0), int(total))
    return round(100.0 * float(bounded) / float(total), decimals)


async def yield_ui():
    """Cede al loop asyncio così NiceGUI può inviare gli aggiornamenti al client."""
    await asyncio.sleep(0)
