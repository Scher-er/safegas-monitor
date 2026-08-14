# SafeGas Monitor — Servidor da Central de Comando (ESQUELETO — Etapa 3)
# ========================================================================

class CentralCommandServer:
    """
    Servidor TCP que recebe TelemetryPackets dos EPIs simulados.
    
    IMPLEMENTAR NA ETAPA 3:
    - Abrir socket TCP e aceitar múltiplos clientes (threading)
    - Receber e desserializar os pacotes JSON
    - Encaminhar para o pipeline: filtragem → LEL → persistência → alerta
    
    PIPELINE COMPLETO (preenchido nas etapas seguintes):
    
    receber_pacote()
        → Etapa 4: filtrar_sinal()
        → Etapa 5: calcular_lel()
        → Etapa 6: persistir()
        → Etapa 7: gerar_laudo() se CRÍTICO
    """

    def __init__(self, host: str, port: int):
        raise NotImplementedError("Implementar na Etapa 3")

    def start(self):
        """Inicia o servidor e entra em loop de aceitação de conexões."""
        raise NotImplementedError("Implementar na Etapa 3")

    def stop(self):
        raise NotImplementedError("Implementar na Etapa 3")

    def _handle_client(self, conn, addr):
        """Thread handler para cada EPI conectado."""
        raise NotImplementedError("Implementar na Etapa 3")
