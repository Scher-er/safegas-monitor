"""
SafeGas Monitor — Componentes da Interface (Rich) — Etapa 8
===========================================================
Gera os painéis e tabelas para a interface gráfica no terminal (TUI),
usando a biblioteca 'rich'.

Layout principal:
  - Cabeçalho: título, estatísticas e status do servidor
  - Tabela 1: Dispositivos Ativos (EPIs conectados e status em tempo real)
  - Tabela 2: Últimos Alertas (histórico recente de anomalias)
  - Tabela 3: Incidentes com Laudo (histórico de eventos CRITICAL)
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from datetime import datetime, timezone
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text
from rich import box

from ui.tui.state import MonitorState

# Cores consistentes com o resto do sistema
_COLORS = {
    "NORMAL":    "bold green",
    "ATTENTION": "bold yellow",
    "WARNING":   "bold dark_orange",
    "CRITICAL":  "bold red",
    "CH4":       "red",
    "CO":        "dark_orange",
    "H2S":       "magenta",
}


class TuiBuilder:
    """Constrói os componentes da interface Rich a partir do estado."""

    def __init__(self, state: MonitorState):
        self._state = state

    # ------------------------------------------------------------------
    def build_header(self) -> Panel:
        """Cria o cabeçalho com estatísticas globais."""
        stats = self._state.stats
        uptime = int(stats["uptime_s"])
        m, s = divmod(uptime, 60)
        h, m = divmod(m, 60)
        uptime_str = f"{h:02d}:{m:02d}:{s:02d}"

        text = Text()
        text.append("SafeGas Monitor — Central de Comando\n", style="bold cyan")
        text.append(f"Uptime: {uptime_str} | ", style="white")
        text.append(f"EPIs Ativos: {stats['devices_count']} | ", style="white")
        text.append(f"Pacotes/s: {stats['throughput_pps']:.1f} | ", style="white")
        text.append(f"Incidentes (Laudos): {stats['incidents_count']}", style="bold red")

        # Alerta intermitente se houver algum dispositivo em estado crítico
        border_style = "red" if self._state.has_any_critical() and (uptime % 2 == 0) else "cyan"

        return Panel(
            text,
            style="white",
            border_style=border_style,
            box=box.ROUNDED,
            expand=True,
        )

    # ------------------------------------------------------------------
    def build_devices_table(self) -> Table:
        """Cria a tabela de EPIs monitorados em tempo real."""
        table = Table(
            title="[bold blue]EPIs em Monitoramento[/]",
            box=box.SIMPLE_HEAD,
            expand=True,
            show_lines=False,
        )

        table.add_column("Última Leitura", justify="center", style="dim")
        table.add_column("ID EPI", justify="left", style="bold white")
        table.add_column("Funcionário", justify="left")
        table.add_column("Risco R (%)", justify="right")
        table.add_column("Nível de Alerta", justify="center")
        table.add_column("T (°C)", justify="right")
        table.add_column("Pacotes", justify="right", style="dim")

        devices = self._state.devices
        if not devices:
            table.add_row("—", "Aguardando conexões...", "—", "—", "—", "—", "—")
            return table

        for d in devices:
            color = _COLORS.get(d.alert_level, "white")
            
            # Animação piscar se crítico
            now_sec = int(datetime.now(timezone.utc).timestamp())
            is_blink = d.alert_level == "CRITICAL" and (now_sec % 2 == 0)
            level_text = Text(d.alert_level, style=f"{color} reverse" if is_blink else color)

            risk_str = f"{d.risk_ratio:.1f}%"
            if d.risk_ratio >= 100.0:
                risk_str = f"[bold red]{risk_str}[/]"

            table.add_row(
                d.last_seen_short,
                d.device_id,
                d.worker_id,
                risk_str,
                level_text,
                f"{d.temperature_c:.1f}",
                str(d.packets_received),
            )

        return table

    # ------------------------------------------------------------------
    def build_history_table(self) -> Table:
        """Cria a tabela com histórico de alertas recentes."""
        table = Table(
            title="[bold yellow]Histórico de Eventos Recentes[/]",
            box=box.SIMPLE_HEAD,
            expand=True,
        )

        table.add_column("Hora", justify="center", style="dim")
        table.add_column("EPI", justify="left", style="bold white")
        table.add_column("Evento", justify="center")
        table.add_column("Risco", justify="right")
        table.add_column("Gases Críticos", justify="left")

        history = self._state.alert_history
        if not history:
            table.add_row("—", "—", "Nenhum evento detectado", "—", "—")
            return table

        for e in history[:15]:  # Mostra apenas os últimos 15
            color = _COLORS.get(e.alert_level, "white")
            level_text = Text(e.alert_level, style=color)
            table.add_row(
                e.ts_short,
                e.device_id,
                level_text,
                f"[{color}]{e.risk_ratio:.1f}%[/]",
                e.gases,
            )

        return table

    # ------------------------------------------------------------------
    def build_incidents_table(self) -> Table:
        """Cria a tabela com laudos gerados."""
        table = Table(
            title="[bold red]Incidentes Críticos Registrados (Laudos LaTeX)[/]",
            box=box.SIMPLE_HEAD,
            expand=True,
        )

        table.add_column("Hora", justify="center", style="dim")
        table.add_column("Incidente ID", justify="left")
        table.add_column("EPI", justify="left", style="bold white")
        table.add_column("Pico de Risco", justify="right", style="bold red")
        table.add_column("Laudo Gerado", justify="left", style="cyan")

        incidents = self._state.incidents
        if not incidents:
            table.add_row("—", "—", "Nenhum incidente crítico", "—", "—")
            return table

        for inc in incidents[:10]: # Mostra últimos 10
            table.add_row(
                inc.ts_short,
                inc.incident_id[:8],
                inc.device_id,
                f"{inc.peak_risk_ratio:.1f}%",
                inc.latex_path,
            )

        return table

    # ------------------------------------------------------------------
    def build_layout(self) -> Layout:
        """Monta o layout completo (tela dividida)."""
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main"),
        )
        layout["main"].split_row(
            Layout(name="left", ratio=2),
            Layout(name="right", ratio=3),
        )
        layout["right"].split_column(
            Layout(name="history", ratio=1),
            Layout(name="incidents", ratio=1),
        )

        layout["header"].update(self.build_header())
        layout["left"].update(Panel(self.build_devices_table(), box=box.ROUNDED))
        layout["history"].update(Panel(self.build_history_table(), box=box.ROUNDED))
        layout["incidents"].update(Panel(self.build_incidents_table(), box=box.ROUNDED))

        return layout
