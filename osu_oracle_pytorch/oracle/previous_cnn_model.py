import torch
import torch.nn.functional as F
from torch import nn

class CNN_Model(nn.Module):
    def __init__(
            self,
            input_channels,
            num_classes,
            max_length=3502,
            dropout_rate=0.5,
    ):
        super(CNN_Model, self).__init__()
        self.conv1 = nn.Conv1d(in_channels=input_channels, out_channels=16, kernel_size=7)
        self.pool1 = nn.MaxPool1d(2)
        self.conv2 = nn.Conv1d(in_channels=16, out_channels=32, kernel_size=5)
        self.pool2 = nn.MaxPool1d(2)
        self.conv3 = nn.Conv1d(in_channels=32, out_channels=64, kernel_size=3)
        self.pool3 = nn.MaxPool1d(2)

        # we need to calculate the exact number of in_features after the flatten...
        with torch.no_grad():
            dummy = torch.zeros(1, input_channels, max_length)

            dummy = self.pool1(F.relu(self.conv1(dummy)))
            dummy = self.pool2(F.relu(self.conv2(dummy)))
            dummy = self.pool3(F.relu(self.conv3(dummy)))

            in_features = dummy.flatten(start_dim=1).shape[1]

        self.fc1 = nn.Linear(in_features, 128)
        self.fc2 = nn.Linear(128, 64)
        self.fc3 = nn.Linear(64, num_classes)

        self.dropout = nn.Dropout(dropout_rate)

    def forward(self, x):
        x = self.pool1(F.relu(self.conv1(x)))
        x = self.pool2(F.relu(self.conv2(x)))
        x = self.pool3(F.relu(self.conv3(x)))

        x = torch.flatten(x, start_dim=1)

        x = F.relu(self.fc1(x))
        x = self.dropout(x)
        x = F.relu(self.fc2(x))
        x = self.dropout(x)

        # classification outputs here
        # x = F.softmax(self.fc3(x)) # not needed with CE Loss
        x = self.fc3(x)

        return x