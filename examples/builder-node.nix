{ ... }:

{
  chuggy.k3s.nodeLabels = [
    "chuggy.dev/node-role=builder"
  ];
  chuggy.k3s.nodeTaints = [
    "chuggy.dev/node-role=builder:NoSchedule"
  ];
}
