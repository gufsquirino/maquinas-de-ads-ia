// Detecta o rosto principal em cada imagem de uma pasta usando o Vision da Apple.
// Saida por linha: arquivo cx cy altura, normalizados com origem no topo esquerdo.
import AppKit
import Foundation
import Vision

let pasta = CommandLine.arguments[1]
let arquivos = try FileManager.default.contentsOfDirectory(atPath: pasta)
    .filter { $0.hasSuffix(".jpg") }
    .sorted()

for nome in arquivos {
    let url = URL(fileURLWithPath: pasta).appendingPathComponent(nome)
    guard let imagem = NSImage(contentsOf: url),
          let cg = imagem.cgImage(forProposedRect: nil, context: nil, hints: nil) else { continue }
    let pedido = VNDetectFaceRectanglesRequest()
    try VNImageRequestHandler(cgImage: cg, options: [:]).perform([pedido])
    guard let rostos = pedido.results, !rostos.isEmpty else { continue }
    let maior = rostos.max { $0.boundingBox.height < $1.boundingBox.height }!
    let c = maior.boundingBox
    print(nome, c.midX, 1 - c.midY, c.height)
}
