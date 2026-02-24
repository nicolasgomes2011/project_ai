"""Integração com Google Docs via OAuth 2.0."""

import os
from pathlib import Path
from typing import Optional

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build


SCOPES = ["https://www.googleapis.com/auth/documents"]


class GoogleDocsClient:
    """Cliente para criar e editar Google Docs via API."""

    def __init__(self, credentials_path: str = "credentials.json", token_path: str = "token.json"):
        self.credentials_path = credentials_path
        self.token_path = token_path
        self._service = None

    def authenticate(self) -> None:
        """Executa fluxo OAuth. Abre browser na primeira vez e salva token.json."""
        creds: Optional[Credentials] = None

        if Path(self.token_path).exists():
            creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not Path(self.credentials_path).exists():
                    raise FileNotFoundError(
                        f"Arquivo de credenciais não encontrado: {self.credentials_path}\n"
                        "Siga as instruções:\n"
                        "1. Acesse: https://console.cloud.google.com/\n"
                        "2. Crie um projeto → Ative 'Google Docs API'\n"
                        "3. Credenciais → Criar → OAuth 2.0 → App desktop\n"
                        f"4. Baixe o JSON e salve como '{self.credentials_path}' na raiz do projeto"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(self.credentials_path, SCOPES)
                creds = flow.run_local_server(port=0)

            with open(self.token_path, "w") as token_file:
                token_file.write(creds.to_json())

        self._service = build("docs", "v1", credentials=creds)

    def _ensure_authenticated(self) -> None:
        if self._service is None:
            self.authenticate()

    def create_document(self, title: str) -> str:
        """Cria um novo Google Doc e retorna o document_id."""
        self._ensure_authenticated()
        doc = self._service.documents().create(body={"title": title}).execute()
        return doc["documentId"]

    def append_text(self, doc_id: str, text: str) -> None:
        """Adiciona texto formatado ao final do documento."""
        self._ensure_authenticated()

        # Obtém o índice final do documento
        doc = self._service.documents().get(documentId=doc_id).execute()
        content = doc.get("body", {}).get("content", [])
        end_index = 1  # mínimo válido
        if content:
            last = content[-1]
            end_index = last.get("endIndex", 1) - 1  # -1 para ficar antes do \n final

        requests = [
            {
                "insertText": {
                    "location": {"index": end_index},
                    "text": text if text.endswith("\n") else text + "\n",
                }
            }
        ]
        self._service.documents().batchUpdate(
            documentId=doc_id, body={"requests": requests}
        ).execute()

    def get_document_url(self, doc_id: str) -> str:
        """Retorna a URL pública do documento."""
        return f"https://docs.google.com/document/d/{doc_id}/edit"
