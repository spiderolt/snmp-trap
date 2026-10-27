# snmp-trap

Agente que recebe SNMP trap da OLT Huawei e envia o evento para o SpiderOLT.

A tela local, na porta HTTP 8088, tem três campos: porta UDP (padrão 1162), endereço da API (exemplo `site.spiderolt.com`) e token. O POST vai sempre para `https://<endereço>/api/snmp-trap/traps`.

O container usa a rede do host para a porta escolhida na tela ser a porta da máquina. A 162 fica com o Zabbix.

## Release

Na branch `main`, dispare o workflow **Release** e informe a versão (`v1.0.0` ou `v1.0`). O workflow testa, publica `ghcr.io/<dono>/snmp-trap:v1.0.0` e cria a tag e o GitHub Release. A versão não é reutilizada em outro commit.

## Instalar

No servidor Linux da rede de gerência, use o script do release mais recente:

```bash
curl -fsSL https://github.com/spiderolt/snmp-trap/releases/latest/download/install.sh | sudo bash
```

Esse script instala o Docker se ele não existir e sobe a imagem daquele release. O repositório pode ficar público: a leitura e o download do release não exigem conta. O pacote da imagem no GHCR também precisa estar público, senão o `docker pull` pede login.
