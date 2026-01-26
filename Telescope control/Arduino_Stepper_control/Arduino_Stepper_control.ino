#include <Wire.h> // I2C library

int Xpos = 0;
int Ypos = 0;
float StepPerDeg = 200/360;

void setup() {
  // put your setup code here, to run once:
  Wire.begin(1);
  Serial.begin(9600);
  Wire.onReceive(NewPos);
}

void loop() {
  // put your main code here, to run repeatedly:
 delay(100);
}

uint16_t readU16(){
  uint8_t hi = Wire.read();
  uint8_t lo = Wire.read();
  return ((uint16_t)hi << 8) | lo;
}


void NewPos(int howMany){
  if (howMany = 4){
    uint16_t NewXpos = readU16();
    uint16_t NewYpos = readU16();
    NewXpos / 100;
    NewYpos / 100;
    Move(NewXpos, NewYpos);
  }

}
void Move(uint16_t NewXpos, uint16_t NewYpos){
  char Xdir = (0<((int)NewXpos - (int)Xpos)) ? "p" : "n";
  char  Ydir = (0<((int)NewYpos - (int)Ypos)) ? "p" : "n";
  float Xstep = (abs((int)NewXpos - (int)Xpos)*StepPerDeg);
  float Ystep = (abs((int)NewYpos - (int)Ypos)*StepPerDeg);
}

