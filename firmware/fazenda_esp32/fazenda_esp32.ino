// FazendaInteligente - agente ESP32
// Le umidade, temperatura e CE do sensor JXCT (Modbus RTU / RS485) e envia
// para a API via HTTP (RF01, RF02, RF03, RNF03/AL07).

#include <WiFi.h>
#include <HTTPClient.h>
#include <ModbusMaster.h>
#include <time.h>

// WIFI_SSID, WIFI_SENHA e API_TOKEN ficam em secrets.h (fora do git).
// Copie secrets.h.example para secrets.h na mesma pasta e preencha.
#include "secrets.h"

// ---------------- CONFIGURACAO ----------------
const char* API_URL = "http://165.22.190.56:8000/leituras";

// Sem id_experimento no envio: a API grava no experimento ativo (o mais recente
// sem data_fim). Criar um experimento novo redireciona o sensor sem regravar.

const unsigned long INTERVALO_LEITURA_MS = 10UL * 60UL * 1000UL;  // RF01: 10 min
const unsigned long INTERVALO_WIFI_MS    = 30UL * 1000UL;         // tentativa de reconexao
const unsigned long INTERVALO_REENVIO_MS = 30UL * 1000UL;         // reenvio da fila
// ----------------------------------------------

#define RXD2 16
#define TXD2 17
#define DE_RE 4

#define TAMANHO_FILA 144  // 24 h de leituras a cada 10 min

ModbusMaster node;

// Tipos declarados antes da 1a funcao: a IDE do Arduino gera os prototipos
// automaticamente nesse ponto, e eles precisam enxergar estes tipos.
enum ResultadoEnvio { ENVIADO, DESCARTAR, TENTAR_DEPOIS };

struct Leitura {
  unsigned long millisLeitura;  // momento da leitura (convertido em UTC no envio)
  float temperatura;
  float umidade;
  float ce;
  bool retransmissao;           // true apos a primeira falha -> status_envio 'R'
};

Leitura fila[TAMANHO_FILA];
int filaInicio = 0;
int filaTamanho = 0;

unsigned long ultimaLeitura = 0;
unsigned long ultimaTentativaWifi = 0;
unsigned long ultimoReenvio = 0;
bool primeiraLeitura = true;

void preTransmission()  { digitalWrite(DE_RE, HIGH); }
void postTransmission() { digitalWrite(DE_RE, LOW); }

// ---------------- Wi-Fi / NTP ----------------

void conectarWifi() {
  Serial.printf("Conectando ao Wi-Fi %s...\n", WIFI_SSID);
  WiFi.disconnect();
  WiFi.begin(WIFI_SSID, WIFI_SENHA);
  ultimaTentativaWifi = millis();
}

void manterWifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  if (millis() - ultimaTentativaWifi >= INTERVALO_WIFI_MS) conectarWifi();
}

bool horaSincronizada() {
  return time(nullptr) > 1700000000;  // posterior a nov/2023
}

// ---------------- Fila ----------------

void enfileirar(const Leitura& l) {
  if (filaTamanho == TAMANHO_FILA) {
    // fila cheia: descarta a mais antiga
    filaInicio = (filaInicio + 1) % TAMANHO_FILA;
    filaTamanho--;
    Serial.println("Fila cheia: leitura mais antiga descartada");
  }
  fila[(filaInicio + filaTamanho) % TAMANHO_FILA] = l;
  filaTamanho++;
}

void desenfileirar() {
  filaInicio = (filaInicio + 1) % TAMANHO_FILA;
  filaTamanho--;
}

// ---------------- Sensor ----------------

bool lerSensor(Leitura& l) {
  for (int tentativa = 1; tentativa <= 3; tentativa++) {
    uint8_t result = node.readHoldingRegisters(0x0000, 3);
    if (result == node.ku8MBSuccess) {
      l.millisLeitura = millis();
      l.umidade       = node.getResponseBuffer(0) / 10.0;
      l.temperatura   = (int16_t)node.getResponseBuffer(1) / 10.0;  // com sinal
      l.ce            = node.getResponseBuffer(2);
      l.retransmissao = false;
      return true;
    }
    Serial.printf("Erro Modbus (tentativa %d): 0x%02X\n", tentativa, result);
    delay(1000);
  }
  return false;
}

// ---------------- Envio ----------------

ResultadoEnvio enviar(const Leitura& l) {
  if (WiFi.status() != WL_CONNECTED) return TENTAR_DEPOIS;

  unsigned long idadeMs = millis() - l.millisLeitura;
  char campoTimestamp[48] = "";

  if (horaSincronizada()) {
    time_t momento = time(nullptr) - (time_t)(idadeMs / 1000);
    struct tm utc;
    gmtime_r(&momento, &utc);
    char ts[24];
    strftime(ts, sizeof(ts), "%Y-%m-%dT%H:%M:%SZ", &utc);
    snprintf(campoTimestamp, sizeof(campoTimestamp), "\"timestamp\":\"%s\",", ts);
  } else if (idadeMs > 30000) {
    // sem NTP e leitura antiga: o servidor carimbaria a hora errada
    return TENTAR_DEPOIS;
  }
  // sem NTP e leitura recente: omite timestamp, servidor usa a hora de chegada

  char json[256];
  snprintf(json, sizeof(json),
           "{%s\"temperatura\":%.1f,\"umidade\":%.1f,"
           "\"ce\":%.1f,\"status_envio\":\"%c\"}",
           campoTimestamp, l.temperatura, l.umidade, l.ce,
           l.retransmissao ? 'R' : 'S');

  HTTPClient http;
  http.setConnectTimeout(5000);
  http.setTimeout(10000);
  http.begin(API_URL);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("Authorization", String("Bearer ") + API_TOKEN);

  int codigo = http.POST((uint8_t*)json, strlen(json));
  String resposta = http.getString();
  http.end();

  Serial.printf("POST %s -> %d\n", json, codigo);

  if (codigo == 201) return ENVIADO;

  Serial.println(resposta);
  // 422 = leitura fora das faixas do banco: reenviar nao resolve
  if (codigo == 400 || codigo == 422) return DESCARTAR;
  // rede, 401, 5xx etc.: mantem na fila
  return TENTAR_DEPOIS;
}

void esvaziarFila() {
  while (filaTamanho > 0) {
    ResultadoEnvio r = enviar(fila[filaInicio]);
    if (r == TENTAR_DEPOIS) {
      fila[filaInicio].retransmissao = true;
      Serial.printf("Envio falhou; %d leitura(s) na fila\n", filaTamanho);
      return;
    }
    if (r == DESCARTAR) Serial.println("Leitura descartada (rejeitada pela API)");
    desenfileirar();
  }
}

// ---------------- setup / loop ----------------

void setup() {
  Serial.begin(115200);
  Serial2.begin(4800, SERIAL_8N1, RXD2, TXD2);

  pinMode(DE_RE, OUTPUT);
  digitalWrite(DE_RE, LOW);

  node.begin(1, Serial2);
  node.preTransmission(preTransmission);
  node.postTransmission(postTransmission);

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  conectarWifi();

  // UTC puro (RF03)
  configTime(0, 0, "pool.ntp.org", "time.google.com");

  // aguarda Wi-Fi e NTP no boot (ate 20 s) para a 1a leitura sair com 'S' e timestamp
  unsigned long inicio = millis();
  while ((WiFi.status() != WL_CONNECTED || !horaSincronizada()) && millis() - inicio < 20000) {
    delay(250);
  }
  Serial.printf("Wi-Fi: %s | NTP: %s\n",
                WiFi.status() == WL_CONNECTED ? WiFi.localIP().toString().c_str() : "desconectado",
                horaSincronizada() ? "ok" : "pendente");

  Serial.println("FazendaInteligente - agente iniciado");
}

void loop() {
  manterWifi();

  if (primeiraLeitura || millis() - ultimaLeitura >= INTERVALO_LEITURA_MS) {
    primeiraLeitura = false;
    ultimaLeitura = millis();

    Leitura l;
    if (lerSensor(l)) {
      Serial.printf("Leitura: T=%.1f C  U=%.1f %%  CE=%.0f uS/cm\n",
                    l.temperatura, l.umidade, l.ce);
      enfileirar(l);
      esvaziarFila();
      ultimoReenvio = millis();
    } else {
      Serial.println("Falha na leitura do sensor neste ciclo");
    }
  }

  if (filaTamanho > 0 && millis() - ultimoReenvio >= INTERVALO_REENVIO_MS) {
    ultimoReenvio = millis();
    esvaziarFila();
  }

  delay(100);
}
