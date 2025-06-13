# Variable naming

As a reminder for myself to stay consistent with naming them

| Data                       | Name       | Description                                                |
| -------------------------- |--------- - | ---------------------------------------------------------- |
| Data received from MQTT    | `message`  | The MQTT payload + some meta data                          |
| MQTT payload               | `envelope` | JSON object with the raw data from `RAMSES_ESP`            |
| JSON `rx` key              | `frame`    | Text string containing the Ramses II data + some meta data |
| RamsesPacket(frame) object | `packet`   | The above `frame` turned into an object                    |
| Code(packet) object        | `payload`  | The decoded `packet` turned into an object                 |
