import copy
import torch
import torch.nn.utils.prune as prune

def prune_models(
    models,
    X_train,
    y_train_numerical,
    initial_sparsity=0.30,
    final_sparsity=0.50, # adjust this based on dataset size, originally 0.70
    fine_tune_epochs=2,
    gradual=True,
    batch_size=16,
    learning_rate=0.0001
):
    pruned_models = []

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    for model_idx, model in enumerate(models):
        print(f"\nPruning model {model_idx + 1}/{len(models)}")

        # Preserve the original model
        pruned_model = copy.deepcopy(model)
        pruned_model.to(device)

        # Layers that will be pruned
        prunable_layers = [
            module
            for module in pruned_model.modules()
            if isinstance(module, (torch.nn.Conv1d, torch.nn.Linear))
        ]

        if gradual:
            # Reproduce:
            # initial_sparsity = 30%
            # final_sparsity   = 70%
            #
            # We prune progressively over the fine-tuning epochs.
            sparsities = torch.linspace(
                initial_sparsity,
                final_sparsity,
                fine_tune_epochs
            ).tolist()

        else:
            # Immediate pruning directly to final sparsity
            sparsities = [final_sparsity]

        # Fine-tuning dataset
        dataset = torch.utils.data.TensorDataset(
            torch.as_tensor(X_train, dtype=torch.float32),
            torch.as_tensor(y_train_numerical, dtype=torch.long)
        )

        dataloader = torch.utils.data.DataLoader(
            dataset,
            batch_size=batch_size,
            shuffle=True
        )

        criterion = torch.nn.CrossEntropyLoss()

        optimizer = torch.optim.Adam(
            pruned_model.parameters(),
            lr=learning_rate
        )

        # ---------------------------------------------------------
        # Pruning / fine-tuning
        # ---------------------------------------------------------

        for epoch, target_sparsity in enumerate(sparsities):

            print(
                f"  Epoch {epoch + 1}/{len(sparsities)} "
                f"- target sparsity: {target_sparsity:.0%}"
            )

            for module in prunable_layers:

                if not hasattr(module, "weight_mask"):
                    # First pruning step
                    prune.l1_unstructured(
                        module,
                        name="weight",
                        amount=target_sparsity
                    )

                else:
                    # Increase sparsity while preserving
                    # the existing pruning mask
                    prune.l1_unstructured(
                        module,
                        name="weight",
                        amount=target_sparsity
                    )

            # Fine-tune after this pruning step
            pruned_model.train()

            running_loss = 0.0

            for inputs, targets in dataloader:

                inputs = inputs.to(device)
                targets = targets.to(device)

                optimizer.zero_grad()

                outputs = pruned_model(inputs)
                loss = criterion(outputs, targets)

                loss.backward()
                optimizer.step()

                running_loss += loss.item()

            average_loss = running_loss / len(dataloader)

            print(
                f"    Fine-tune loss: {average_loss:.4f}"
            )

        # ---------------------------------------------------------
        # Make pruning permanent
        # ---------------------------------------------------------

        for module in prunable_layers:
            if hasattr(module, "weight_mask"):
                prune.remove(module, "weight")

        pruned_model.eval()
        pruned_models.append(pruned_model)

    return pruned_models