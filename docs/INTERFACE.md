# Graphical Interface - Application Visual Guide

## Window Layout

```
┌─────────────────────────────────────────────────────────┐
│                       Omnicom v1.0                    │
├─────────────────────────────────────────────────────────┤
│                                                         │
│                     Omnicom v1.0                      │
│                                                         │
│  ┌────────────────────────────────────────────────┐   │
│  │  Port Configuration                           │   │
│  ├────────────────────────────────────────────────┤   │
│  │                                                │   │
│  │  Port Type:    [USB (/dev/ttyUSB*)         ▼] │   │
│  │                                                │   │
│  │  Port:         [/dev/ttyUSB0               ▼] │   │
│  │                                                │   │
│  └────────────────────────────────────────────────┘   │
│                                                         │
│  ┌────────────────────────────────────────────────┐   │
│  │  Communication Parameters                     │   │
│  ├────────────────────────────────────────────────┤   │
│  │                                                │   │
│  │  Baud Rate:         [115200                ▼]  │   │
│  │                     └─────────────────────┘   │   │
│  │                      (highlighted in blue)    │   │
│  │                                                │   │
│  │  Data Bits:         [8                     ▼] │   │
│  │                                                │   │
│  │  Parity:            [None                  ▼] │   │
│  │                                                │   │
│  │  Stop Bits:         [1                     ▼] │   │
│  │                                                │   │
│  │  Flow Control:      [None                  ▼] │   │
│  │                                                │   │
│  └────────────────────────────────────────────────┘   │
│                                                         │
│            ┌───────────────────────────┐               │
│            │      CONNECT              │               │
│            └───────────────────────────┘               │
│               (large green button)                     │
│                                                         │
│              Ready to connect                          │
│              (status in green)                         │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

## Visual Characteristics

### Colors and Styles

- **Background**: Light gray (#f5f5f5)
- **Groups**: White background with rounded borders
- **Baud Rate Field**: Blue highlight (#e3f2fd) with blue border (#2196f3)
- **Connect Button**: Green (#4caf50) with hover effect
- **Status**:
  - Green: Ready
  - Orange: Connecting
  - Blue: Waiting for password
  - Red: Error

### Interactions

1. **ComboBox Hover**: Border changes to blue
2. **Button Hover**: Darker green
3. **Button Click**: Even darker green
4. **Port Type Change**: Automatically updates list

### Dialogs

When you click CONNECT:

```
┌─────────────────────────────────────┐
│  ⓘ  Connection Started              │
├─────────────────────────────────────┤
│                                     │
│  Picocom terminal opened.           │
│                                     │
│  Port: /dev/ttyUSB0                 │
│  Baud Rate: 115200 baud             │
│  Configuration: 8N1                 │
│                                     │
│  Use Ctrl+A Ctrl+X to exit          │
│  picocom                            │
│                                     │
│           ┌────────┐                │
│           │   OK   │                │
│           └────────┘                │
└─────────────────────────────────────┘
```

### Responsiveness

- Fixed size: 550x500 pixels
- Consistent spacing: 15-20px
- Fields with adequate minimum height
- Labels aligned to the left
- Inputs occupy full available width

## Usage Flow

1. **Port Selection**
   - Choose between Serial or USB
   - List updates automatically
   - Port counter in status

2. **Configuration**
   - Baud rate is the main field (highlighted)
   - Safe default values (9600, 8N1)
   - All combos with common options

3. **Connection**
   - Click green button
   - Status changes to "Connecting..."
   - Terminal opens automatically
   - Informative dialog appears
   - Status indicates "enter password"

4. **picocom Terminal**
   - Opens in separate window
   - Requests sudo password
   - Starts serial communication
   - Ctrl+A Ctrl+X to exit
