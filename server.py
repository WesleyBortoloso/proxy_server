import socket
import ssl
import urllib.parse
import hashlib
import os
import argparse
import logging

# Configuração do logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

cache_dir = "cache"
if not os.path.exists(cache_dir):
    try:
        os.makedirs(cache_dir)
        logging.info(f"Pasta de cache criada: {cache_dir}")
    except OSError as e:
        logging.error(f"Erro ao criar o diretório de cache: {e}")

def get_cache_filename(url):
    """Gera o nome do arquivo de cache com base no hash MD5 da URL."""
    cache_key = hashlib.md5(url.encode()).hexdigest()
    return os.path.join(cache_dir, cache_key)

def handle_https_request(client_socket, method, url):
    """Manipula as requisições HTTPS (via túnel CONNECT)."""
    parsed_url = urllib.parse.urlparse(url)
    host = parsed_url.hostname
    port = parsed_url.port if parsed_url.port else 443

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
            server_socket.connect((host, port))
            server_socket = ssl.wrap_socket(server_socket)
            
            client_socket.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            
            while True:
                client_data = client_socket.recv(4096)
                if not client_data:
                    break
                server_socket.sendall(client_data)

                server_data = server_socket.recv(4096)
                if not server_data:
                    break
                client_socket.sendall(server_data)

    except Exception as e:
        logging.error(f"Erro ao estabelecer túnel HTTPS com {host}: {e}")
        client_socket.sendall(b"HTTP/1.1 500 Internal Server Error\r\n\r\n")
    
    client_socket.close()

def handle_client_request(client_socket):
    """Função que recebe a requisição do cliente, redireciona ao servidor e responde ao cliente."""
    try:
        request = client_socket.recv(4096)
        logging.debug(f"Recebendo dados do cliente: {request}")  # Log para depuração
        first_line = request.split(b'\n')[0]
        method, url, _ = first_line.split()

        # Caso seja uma requisição CONNECT (HTTPS)
        if method == b'CONNECT':
            handle_https_request(client_socket, method, url)
            return

        # Caso o método não seja GET ou POST
        if method not in [b'GET', b'POST']:
            client_socket.sendall(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
            client_socket.close()
            return

        # Parse da URL
        parsed_url = urllib.parse.urlparse(url.decode() if url.startswith(b'http') else 'http://' + url.decode().lstrip('/'))
        host = parsed_url.hostname
        path = parsed_url.path or '/'

        # Verificação do host
        if not host:
            client_socket.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
            client_socket.close()
            return

        # Verificando se a resposta está no cache
        cache_filename = get_cache_filename(url.decode())
        if method == b'GET' and os.path.exists(cache_filename):
            logging.info(f"Resposta encontrada no cache para: {url.decode()}")
            with open(cache_filename, 'rb') as cache_file:
                cached_response = cache_file.read()
            client_socket.sendall(cached_response)
            client_socket.close()
            return

        # Conexão com o servidor de destino
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
            server_socket.connect((host, 80))
            logging.info(f"Conectado ao servidor {host}")

            if method == b'GET':
                full_request = f"GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode()
            elif method == b'POST':
                headers = request.split(b'\n')[1:]
                content_length = 0
                for header in headers:
                    if b'Content-Length' in header:
                        content_length = int(header.split(b':')[1].strip())
                
                # Corpo da requisição POST
                body = request.split(b'\r\n\r\n')[1] if content_length > 0 else b''

                logging.debug(f"Corpo da requisição POST: {body[:100]}")  # Mostra os primeiros 100 bytes

                full_request = f"POST {path} HTTP/1.1\r\nHost: {host}\r\nContent-Length: {content_length}\r\nConnection: close\r\n\r\n".encode() + body

            server_socket.sendall(full_request)

            response = b""
            while True:
                data = server_socket.recv(4096)
                if not data:
                    break
                response += data

            # Verificação de erros no servidor
            if b"404 Not Found" in response:
                logging.error("Erro 404 - Página não encontrada.")
            elif b"403 Forbidden" in response:
                logging.error("Erro 403 - Acesso proibido.")
            elif b"500 Internal Server Error" in response:
                logging.error("Erro 500 - Problema no servidor.")
            
            # Armazenando a resposta no cache (para GET e POST)
            if method in [b'GET', b'POST'] and response:
                try:
                    logging.info(f"Armazenando a resposta no cache para: {url.decode()}")
                    with open(cache_filename, 'wb') as cache_file:
                        cache_file.write(response)
                    logging.info(f"Arquivo de cache salvo em: {cache_filename}")
                except Exception as e:
                    logging.error(f"Erro ao salvar o arquivo de cache: {e}")

            client_socket.sendall(response)

    except Exception as e:
        logging.error(f"Erro ao processar a requisição: {e}")
        client_socket.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
    
    client_socket.close()

def start_proxy_server(ip, port):
    """Inicia o servidor proxy."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.bind((ip, port))
        server_socket.listen(5)
        logging.info(f"Servidor proxy em execução em {ip}:{port}")

        while True:
            client_socket, client_address = server_socket.accept()
            logging.info(f"Conexão recebida de {client_address}")
            handle_client_request(client_socket)

def main():
    """Função principal para capturar o IP e a porta da linha de comando."""
    parser = argparse.ArgumentParser(description="Inicia um servidor proxy.")
    parser.add_argument("ip", type=str, help="Endereço IP no qual o proxy vai escutar.")
    parser.add_argument("port", type=int, help="Porta na qual o proxy vai escutar.")
    args = parser.parse_args()

    start_proxy_server(args.ip, args.port)

if __name__ == "__main__":
    main()
