# SafeGas Monitor — Cliente Socket (EPI → Central) (ESQUELETO — Etapa 3)
# =======================================================================

class EPISocketClient:
    """
    Cliente TCP que envia TelemetryPackets para a Central de Comando.
    
    IMPLEMENTAR NA ETAPA 3:
    - Conectar ao servidor via socket TCP
    - Enviar pacotes JSON serializados
    - Tratar reconexão automática em caso de falha
    - Prefixar mensagens com tamanho (length-prefixed framing)
    """

    def __init__(self, host: str, port: int):
        raise NotImplementedError("Implementar na Etapa 3")

    def connect(self):
        raise NotImplementedError("Implementar na Etapa 3")

    def send_packet(self, packet) -> bool:
        """Envia um TelemetryPacket. Retorna True se enviado com sucesso."""
        raise NotImplementedError("Implementar na Etapa 3")

    def disconnect(self):
        raise NotImplementedError("Implementar na Etapa 3")
