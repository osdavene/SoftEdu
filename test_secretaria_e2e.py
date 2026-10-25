import urllib.request
import urllib.parse
import json
import uuid

BASE_URL = "http://127.0.0.1:8000/api/v1"

def test_full_secretaria_lifecycle():
    print("=== TEST COMPLETO DE SECRETARÍA ACADÉMICA (E2E) ===")

    # 1. Login Secretaría
    login_payload = json.dumps({
        "email": "secretaria@gimnasiosanangel.edu.co",
        "password": "SoftEdu2026*"
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{BASE_URL}/auth/login",
        data=login_payload,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        auth_data = json.loads(resp.read().decode("utf-8"))
        token = auth_data["access_token"]
        print(f"[OK] 1. Login exitoso como Secretaría: {auth_data['user']['full_name']} ({auth_data['user']['role']})")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }

    # 2. Verificar /auth/me
    req = urllib.request.Request(f"{BASE_URL}/auth/me", headers=headers)
    with urllib.request.urlopen(req) as resp:
        me_data = json.loads(resp.read().decode("utf-8"))
        assert me_data["role"] == "SECRETARIA"
        print(f"[OK] 2. Verificación de perfil /auth/me correcta (Rol: {me_data['role']})")

    # 3. Listar estudiantes
    req = urllib.request.Request(f"{BASE_URL}/academic/students", headers=headers)
    with urllib.request.urlopen(req) as resp:
        students = json.loads(resp.read().decode("utf-8"))
        assert len(students) > 0
        print(f"[OK] 3. Listado de estudiantes: {len(students)} registrados.")

    # 4. Matricular nuevo estudiante con datos oficiales SIMAT
    new_doc = f"10{uuid.uuid4().hex[:7]}"
    new_code = f"COL-2026-{uuid.uuid4().hex[:4].upper()}"
    student_payload = json.dumps({
        "email": f"aspirante.{uuid.uuid4().hex[:5]}@gimnasiosanangel.edu.co",
        "password": "SoftEdu2026*",
        "first_name": "Valentina",
        "last_name": "Montoya Gómez",
        "document_number": new_doc,
        "student_code": new_code,
        "grade_level_code": "GRADO_11",
        "group_code": "11-1",
        "document_type": "TI",
        "blood_type": "O+",
        "health_provider_eps": "Sanitas EPS",
        "socioeconomic_stratum": 4,
        "disability_condition": "Ninguna",
        "medical_notes_allergies": "Alergia leve a ácaros y polen.",
        "guardian_name": "Dra. Patricia Gómez",
        "guardian_phone": "+57 312 998 1122"
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{BASE_URL}/academic/students",
        data=student_payload,
        headers=headers
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status in (200, 201)
        new_student = json.loads(resp.read().decode("utf-8"))
        new_stu_id = new_student["id"]
        print(f"[OK] 4. Matrícula SIMAT exitosa: {new_student['full_name']} (ID: {new_stu_id})")

    # 5. Obtener dossier del nuevo estudiante
    req = urllib.request.Request(f"{BASE_URL}/academic/students/{new_stu_id}/dossier", headers=headers)
    with urllib.request.urlopen(req) as resp:
        dossier = json.loads(resp.read().decode("utf-8"))
        docs = dossier["documents"]
        guardians = dossier["guardians"]
        grad_req = dossier["graduation_requirement"]
        assert len(docs) > 0, "Debe generar checklist dinámico"
        assert len(guardians) > 0, "Debe registrar acudiente"
        assert grad_req is not None, "Estudiante de Grado 11° debe tener requisitos de grado inicializados"
        print(f"[OK] 5. Expediente digital cargado: {len(docs)} documentos en checklist, {len(guardians)} acudiente, horas SS: {grad_req['social_service_hours']}")

    # 6. Actualizar estado de un documento a APROBADO
    doc_id = docs[0]["id"]
    doc_patch_payload = json.dumps({
        "status": "APROBADO",
        "observations": "Documento verificado y autenticado con registro notarial.",
        "verified_by_user": "Secretaría Académica"
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/academic/student-documents/{doc_id}/status",
        data=doc_patch_payload,
        headers=headers,
        method="PATCH"
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        updated_doc = json.loads(resp.read().decode("utf-8"))
        assert updated_doc["status"] == "APROBADO"
        print(f"[OK] 6. Checklist documental actualizado: '{updated_doc['document_name']}' -> {updated_doc['status']}")

    # 7. Actualizar requisitos de Grado 11° (80 horas servicio social, ICFES Saber 11)
    grad_patch_payload = json.dumps({
        "social_service_hours": 85,
        "social_service_approved": True,
        "icfes_registration_code": "AC2026119842",
        "icfes_score": 395,
        "prior_certificates_complete": True,
        "administrative_paz_salvo": True,
        "diploma_folio_number": "FOL-11-2026-088"
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/academic/graduation-requirements/{new_stu_id}",
        data=grad_patch_payload,
        headers=headers,
        method="PATCH"
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        updated_grad = json.loads(resp.read().decode("utf-8"))
        assert updated_grad["social_service_hours"] == 85
        assert updated_grad["graduation_status"] == "APTO_PARA_GRADO"
        print(f"[OK] 7. Control de Grado 11° actualizado: {updated_grad['social_service_hours']}h -> Dictamen: {updated_grad['graduation_status']}")

    # 8. Listar y conmutar ventanillas de notas
    req = urllib.request.Request(f"{BASE_URL}/academic/grading-windows", headers=headers)
    with urllib.request.urlopen(req) as resp:
        windows = json.loads(resp.read().decode("utf-8"))
        assert len(windows) > 0
        target_win = windows[0]
        print(f"[OK] 8. Ventanilla de notas consultada: {target_win['period_label']} (Abierta: {target_win['is_open']})")

    toggle_payload = json.dumps({
        "is_open": not target_win["is_open"],
        "extemporaneous_active": False
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/academic/grading-windows/{target_win['id']}/toggle",
        data=toggle_payload,
        headers=headers,
        method="PATCH"
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        toggled_win = json.loads(resp.read().decode("utf-8"))
        print(f"[OK] 8b. Ventanilla conmutada con éxito: ahora is_open = {toggled_win['is_open']}")
        # Restaurar a True
        if not toggled_win["is_open"]:
            restore_req = urllib.request.Request(
                f"{BASE_URL}/academic/grading-windows/{target_win['id']}/toggle",
                data=json.dumps({"is_open": True, "extemporaneous_active": False}).encode("utf-8"),
                headers=headers,
                method="PATCH"
            )
            with urllib.request.urlopen(restore_req):
                pass

    # 9. Generar constancia oficial de estudio
    cert_payload = json.dumps({
        "student_id": new_stu_id,
        "certificate_type": "CONSTANCIA_ESTUDIO",
        "recipient_entity": "Caja de Compensación Familiar Compensar"
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/academic/certificates/generate",
        data=cert_payload,
        headers=headers
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status in (200, 201)
        cert = json.loads(resp.read().decode("utf-8"))
        verif_code = cert["verification_code"]
        assert "SECRETARÍA ACADÉMICA" in cert["content_html"]
        print(f"[OK] 9. Constancia oficial emitida con código: {verif_code}")

    # 10. Validar autenticidad de la constancia mediante endpoint público de verificación
    req = urllib.request.Request(f"{BASE_URL}/academic/certificates/verify/{urllib.parse.quote(verif_code)}")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        verified = json.loads(resp.read().decode("utf-8"))
        assert verified["is_valid"] is True
        assert verified["student_code"] == new_code
        print(f"[OK] 10. Validador QR / Código Alfanumérico exitoso: Certificado de {verified['student_full_name']} auténtico.")

    # 11. Descargar plano oficial SIMAT en CSV
    req = urllib.request.Request(f"{BASE_URL}/academic/simat/export", headers=headers)
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        csv_content = resp.read().decode("utf-8-sig")
        lines = csv_content.strip().split("\n")
        header = lines[0]
        assert "CODIGO_DANE" in header
        assert "TIPO_DOCUMENTO" in header
        assert "NUMERO_DOCUMENTO" in header
        assert "ESTRATO" in header
        assert "EPS" in header
        print(f"[OK] 11. Exportación SIMAT CSV exitosa: {len(lines)} registros (incluye cabecera con variables legales MEN).")

    print("\n>>> ¡TODAS LAS PRUEBAS DE SECRETARÍA ACADÉMICA (E2E) PASARON EXITOSAMENTE! <<<")

if __name__ == "__main__":
    test_full_secretaria_lifecycle()
