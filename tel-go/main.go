package main

import (
	"bytes"
	"database/sql"
	"encoding/csv"
	"encoding/json"
	"fmt"
	"html/template"
	"io"
	"log"
	"math"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/xuri/excelize/v2"
	_ "modernc.org/sqlite"
)

// ==========================================
// Configurations & Global Variables
// ==========================================
var (
	PORT         = "8080"
	ROOT_PATH    = ""
	DB_FILE      = "phonebook.db"
	LOG_FILE     = "phonebook.log"
	db           *sql.DB
	globalLogger *log.Logger
)

type Contact struct {
	ID       int    `json:"id"`
	Location string `json:"location"`
	Unit     string `json:"unit"`
	Name     string `json:"name"`
	Phone1   string `json:"phone1"`
	Phone2   string `json:"phone2"`
}

func init() {
	// بارگذاری متغیرهای محیطی ساده
	if envPort := os.Getenv("PORT"); envPort != "" {
		PORT = envPort
	}
	if envRoot := os.Getenv("ROOT_PATH"); envRoot != "" {
		ROOT_PATH = envRoot
	}

	// راه‌اندازی سیستم لاگ‌نویسی مشابه پایتون
	logFile, err := os.OpenFile(LOG_FILE, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0666)
	if err != nil {
		log.Fatalf("Error creating log file: %v", err)
	}
	globalLogger = log.New(logFile, "", log.LstdFlags)
	globalLogger.Println("Starting Exirpooyan Phonebook in Golang...")
}

// ==========================================
// Database Setup & Manager
// ==========================================
func initDB() {
	var err error
	db, err = sql.Open("sqlite", DB_FILE)
	if err != nil {
		globalLogger.Fatalf("Database Connection Error: %v", err)
	}

	// ایجاد جداول اصلی در صورت عدم وجود
	_, err = db.Exec(`
		CREATE TABLE IF NOT EXISTS contacts (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			location TEXT,
			unit TEXT,
			name TEXT,
			phone1 TEXT,
			phone2 TEXT
		);
		CREATE TABLE IF NOT EXISTS settings (
			key TEXT PRIMARY KEY,
			value TEXT
		);
	`)
	if err != nil {
		globalLogger.Fatalf("Table Creation Error: %v", err)
	}

	// بررسی لزوم افزودن ستون location (مهاجرت دیتابیس)
	rows, err := db.Query("PRAGMA table_info(contacts)")
	if err == nil {
		hasLocation := false
		for rows.Next() {
			var cid int
			var name, ctype string
			var notnull, dflt_value, pk int
			if err := rows.Scan(&cid, &name, &ctype, &notnull, &dflt_value, &pk); err == nil {
				if name == "location" {
					hasLocation = true
				}
			}
		}
		rows.Close()
		if !hasLocation {
			_, _ = db.Exec("ALTER TABLE contacts ADD COLUMN location TEXT DEFAULT 'دفتر مرکزی'")
			globalLogger.Println("Database altered: added 'location' column.")
		}
	}

	// افزودن اطلاعات کاربری پیش‌فرض ادمین در صورت خالی بودن
	var exists int
	_ = db.QueryRow("SELECT COUNT(*) FROM settings WHERE key='username'").Scan(&exists)
	if exists == 0 {
		_, _ = db.Exec("INSERT INTO settings (key, value) VALUES ('username', 'admin')")
		_, _ = db.Exec("INSERT INTO settings (key, value) VALUES ('password', 'admin')")
		globalLogger.Println("Default admin credentials created.")
	}
}

func getCredentials() (string, string) {
	var user, pwd string
	_ = db.QueryRow("SELECT value FROM settings WHERE key='username'").Scan(&user)
	_ = db.QueryRow("SELECT value FROM settings WHERE key='password'").Scan(&pwd)
	if user == "" {
		user = "admin"
	}
	if pwd == "" {
		pwd = "admin"
	}
	return user, pwd
}

func updateCredentials(user, pwd string) error {
	_, err := db.Exec("UPDATE settings SET value=? WHERE key='username'", user)
	if err != nil {
		return err
	}
	_, err = db.Exec("UPDATE settings SET value=? WHERE key='password'", pwd)
	return err
}

func getAllContacts() []Contact {
	var list []Contact
	rows, err := db.Query("SELECT id, location, unit, name, phone1, phone2 FROM contacts ORDER BY location, unit, name")
	if err != nil {
		globalLogger.Printf("Error fetching contacts: %v", err)
		return list
	}
	defer rows.Close()

	for rows.Next() {
		var c Contact
		if err := rows.Scan(&c.ID, &c.Location, &c.Unit, &c.Name, &c.Phone1, &c.Phone2); err == nil {
			list = append(list, c)
		}
	}
	return list
}

// ==========================================
// Levenshtein & Normalization Logic (RAM Search)
// ==========================================
func normalizePersian(text string) string {
	text = strings.TrimSpace(strings.ToLower(text))
	replacements := map[rune]rune{
		'ي': 'ی', 'ك': 'ک', 'ة': 'ه', 'أ': 'ا', 'إ': 'ا', 'آ': 'ا', '‌': ' ',
	}
	var b strings.Builder
	for _, r := range text {
		if rep, ok := replacements[r]; ok {
			b.WriteRune(rep)
		} else {
			b.WriteRune(r)
		}
	}
	return b.String()
}

func levenshteinDistance(s1, s2 string) int {
	r1, r2 := []rune(s1), []rune(s2)
	len1, len2 := len(r1), len(r2)
	if len1 == 0 {
		return len2
	}
	if len2 == 0 {
		return len1
	}

	row := make([]int, len2+1)
	for j := 0; j <= len2; j++ {
		row[j] = j
	}

	for i := 1; i <= len1; i++ {
		prev := i
		for j := 1; j <= len2; j++ {
			val := row[j-1]
			if r1[i-1] != r2[j-1] {
				val++
			}
			if row[j]+1 < val {
				val = row[j] + 1
			}
			if prev+1 < val {
				val = prev + 1
			}
			row[j-1] = prev
			prev = val
		}
		row[len2] = prev
	}
	return row[len2]
}

func levenshteinSimilarity(s1, s2 string) float64 {
	if s1 == "" || s2 == "" {
		return 0.0
	}
	dist := levenshteinDistance(s1, s2)
	maxLen := math.Max(float64(len([]rune(s1))), float64(len([]rune(s2))))
	return 1.0 - (float64(dist) / maxLen)
}

func searchContactsInRAM(query string, all []Contact) ([]Contact, []Contact, bool) {
	queryNorm := normalizePersian(query)
	if queryNorm == "" {
		return nil, nil, false
	}

	var directMatches []Contact
	var fuzzyMatches []struct {
		score float64
		item  Contact
	}

	queryTokens := strings.Fields(queryNorm)

	for _, c := range all {
		nameNorm := normalizePersian(c.Name)
		p1Norm := normalizePersian(c.Phone1)
		p2Norm := normalizePersian(c.Phone2)
		unitNorm := normalizePersian(c.Unit)
		locNorm := normalizePersian(c.Location)

		// ۱. تطابق مستقیم زیررشته‌ها
		if strings.Contains(nameNorm, queryNorm) ||
			strings.Contains(p1Norm, queryNorm) ||
			strings.Contains(p2Norm, queryNorm) ||
			strings.Contains(unitNorm, queryNorm) ||
			strings.Contains(locNorm, queryNorm) {
			directMatches = append(directMatches, c)
			continue
		}

		// ۲. تطابق توکن‌ها (جابجایی اسامی فیلدها)
		if len(queryTokens) > 0 {
			allTokensInName := true
			allTokensInUnit := true
			for _, tok := range queryTokens {
				if !strings.Contains(nameNorm, tok) {
					allTokensInName = false
				}
				if !strings.Contains(unitNorm, tok) {
					allTokensInUnit = false
				}
			}
			if allTokensInName || allTokensInUnit {
				directMatches = append(directMatches, c)
				continue
			}
		}

		// ۳. تخمین فازی با الگوریتم تشابه فاصله ویرایشی
		simScore := levenshteinSimilarity(queryNorm, nameNorm)
		maxTokenScore := 0.0
		nameTokens := strings.Fields(nameNorm)
		for _, qTok := range queryTokens {
			for _, nTok := range nameTokens {
				score := levenshteinSimilarity(qTok, n_tok)
				if score > maxTokenScore {
					maxTokenScore = score
				}
			}
		}
		bestScore := math.Max(simScore, maxTokenScore)
		if bestScore >= 0.5 {
			fuzzyMatches = append(fuzzyMatches, struct {
				score float64
				item  Contact
			}{bestScore, c})
		}
	}

	if len(directMatches) > 0 {
		return directMatches, nil, false
	}

	// مرتب‌سازی نتایج تشابه فازی
	for i := 0; i < len(fuzzyMatches); i++ {
		for j := i + 1; j < len(fuzzyMatches); j++ {
			if fuzzyMatches[i].score < fuzzyMatches[j].score {
				fuzzyMatches[i], fuzzyMatches[j] = fuzzyMatches[j], fuzzyMatches[i]
			}
		}
	}

	var finalFuzzy []Contact
	for i := 0; i < len(fuzzyMatches) && i < 5; i++ {
		finalFuzzy = append(finalFuzzy, fuzzyMatches[i].item)
	}

	return nil, finalFuzzy, len(finalFuzzy) > 0
}

// Helper: تطبیق عنوان ستون‌های اکسل به زبان‌های مختلف
func findColIndex(headers []string, keywords []string, defaultIdx int) int {
	for i, h := range headers {
		hNorm := strings.ToLower(strings.TrimSpace(h))
		for _, kw := range keywords {
			if strings.Contains(hNorm, kw) {
				return i
			}
		}
	}
	return defaultIdx
}

// ==========================================
// Web Controllers (Handlers)
// ==========================================
func handleMain(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/" {
		http.NotFound(w, r)
		return
	}

	themeCookie, err := r.Cookie("dark_mode")
	darkClass := "body--light"
	if err == nil && themeCookie.Value == "true" {
		darkClass = "body--dark"
	} else if err == nil && themeCookie.Value == "null" {
		darkClass = "" // Auto
	}

	tmpl := template.Must(template.New("index").Parse(HTML_TEMPLATE))
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	_ = tmpl.Execute(w, map[string]interface{}{
		"ThemeClass": darkClass,
		"Contacts":   getAllContacts(),
	})
}

// هندلر API جستجوی زنده (Live Search JSON Endpoint)
func handleAPISearch(w http.ResponseWriter, r *http.Request) {
	query := r.URL.Query().Get("q")
	all := getAllContacts()
	direct, fuzzy, isFuzzy := searchContactsInRAM(query, all)

	resp := map[string]interface{}{
		"direct":   direct,
		"fuzzy":    fuzzy,
		"is_fuzzy": isFuzzy,
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(resp)
}

func handleThemeToggle(w http.ResponseWriter, r *http.Request) {
	val := r.URL.Query().Get("val")
	http.SetCookie(w, &http.Cookie{
		Name:    "dark_mode",
		Value:   val,
		Expires: time.Now().Add(365 * 24 * time.Hour),
		Path:    "/",
	})
	w.WriteHeader(http.StatusOK)
}

func handleLogin(w http.ResponseWriter, r *http.Request) {
	if r.Method == "GET" {
		tmpl := template.Must(template.New("login").Parse(LOGIN_TEMPLATE))
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		_ = tmpl.Execute(w, nil)
		return
	}

	user := r.FormValue("username")
	pwd := r.FormValue("password")
	vUser, vPwd := getCredentials()

	if user == vUser && pwd == vPwd {
		http.SetCookie(w, &http.Cookie{
			Name:    "admin_session",
			Value:   "authenticated",
			Expires: time.Now().Add(12 * time.Hour),
			Path:    "/",
		})
		http.Redirect(w, r, "/admin", http.StatusSeeOther)
		return
	}
	http.Redirect(w, r, "/login?error=true", http.StatusSeeOther)
}

func handleLogout(w http.ResponseWriter, r *http.Request) {
	http.SetCookie(w, &http.Cookie{
		Name:    "admin_session",
		Value:   "",
		Expires: time.Now().Add(-1 * time.Hour),
		Path:    "/",
	})
	http.Redirect(w, r, "/", http.StatusSeeOther)
}

func handleAdmin(w http.ResponseWriter, r *http.Request) {
	cookie, err := r.Cookie("admin_session")
	if err != nil || cookie.Value != "authenticated" {
		http.Redirect(w, r, "/login", http.StatusSeeOther)
		return
	}

	tmpl := template.Must(template.New("admin").Parse(ADMIN_TEMPLATE))
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	_ = tmpl.Execute(w, map[string]interface{}{
		"Contacts": getAllContacts(),
	})
}

func handleAdminCredentials(w http.ResponseWriter, r *http.Request) {
	cookie, err := r.Cookie("admin_session")
	if err != nil || cookie.Value != "authenticated" {
		http.Error(w, "Unauthorized", http.StatusUnauthorized)
		return
	}

	user := r.FormValue("username")
	pwd := r.FormValue("password")
	if strings.TrimSpace(user) == "" || strings.TrimSpace(pwd) == "" {
		http.Redirect(w, r, "/admin?status=empty", http.StatusSeeOther)
		return
	}

	err = updateCredentials(user, pwd)
	if err != nil {
		http.Redirect(w, r, "/admin?status=error", http.StatusSeeOther)
		return
	}
	globalLogger.Println("Admin credentials updated successfully.")
	http.Redirect(w, r, "/admin?status=success", http.StatusSeeOther)
}

func handleAdminClear(w http.ResponseWriter, r *http.Request) {
	cookie, err := r.Cookie("admin_session")
	if err != nil || cookie.Value != "authenticated" {
		http.Error(w, "Unauthorized", http.StatusUnauthorized)
		return
	}

	_, err = db.Exec("DELETE FROM contacts")
	if err != nil {
		http.Redirect(w, r, "/admin?status=error", http.StatusSeeOther)
		return
	}
	globalLogger.Println("Database cleared by admin.")
	http.Redirect(w, r, "/admin?status=cleared", http.StatusSeeOther)
}

func handleDownloadSample(w http.ResponseWriter, r *http.Request) {
	f := excelize.NewFile()
	defer f.Close()
	
	ws := "Sheet1"
	f.SetCellValue(ws, "A1", "محل کار")
	f.SetCellValue(ws, "B1", "واحد/بخش")
	f.SetCellValue(ws, "C1", "نام و نام خانوادگی")
	f.SetCellValue(ws, "D1", "تلفن اول")
	f.SetCellValue(ws, "E1", "تلفن دوم")

	f.SetCellValue(ws, "A2", "دفتر تهران")
	f.SetCellValue(ws, "B2", "فناوری اطلاعات")
	f.SetCellValue(ws, "C2", "علی احمدی")
	f.SetCellValue(ws, "D2", "09120000000")
	f.SetCellValue(ws, "E2", "02188888888")

	f.SetCellValue(ws, "A3", "کارخانه اراک")
	f.SetCellValue(ws, "B3", "تولید")
	f.SetCellValue(ws, "C3", "رضا کریمی")
	f.SetCellValue(ws, "D3", "08633333333")
	f.SetCellValue(ws, "E3", "داخلی 112")

	w.Header().Set("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
	w.Header().Set("Content-Disposition", "attachment; filename=Exirpooyan_Sample.xlsx")
	_ = f.Write(w)
}

func handleBackup(w http.ResponseWriter, r *http.{
	f := excelize.NewFile()
	defer f.Close()

	ws := "Sheet1"
	f.SetCellValue(ws, "A1", "محل کار")
	f.SetCellValue(ws, "B1", "واحد/بخش")
	f.SetCellValue(ws, "C1", "نام و نام خانوادگی")
	f.SetCellValue(ws, "D1", "تلفن اول")
	f.SetCellValue(ws, "E1", "تلفن دوم")

	contacts := getAllContacts()
	for i, c := range contacts {
		row := i + 2
		f.SetCellValue(ws, fmt.Sprintf("A%d", row), c.Location)
		f.SetCellValue(ws, fmt.Sprintf("B%d", row), c.Unit)
		f.SetCellValue(ws, fmt.Sprintf("C%d", row), c.Name)
		f.SetCellValue(ws, fmt.Sprintf("D%d", row), c.Phone1)
		f.SetCellValue(ws, fmt.Sprintf("E%d", row), c.Phone2)
	}

	w.Header().Set("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
	w.Header().Set("Content-Disposition", "attachment; filename=Exirpooyan_Backup.xlsx")
	_ = f.Write(w)
}

func handleAdminUpload(w http.ResponseWriter, r *http.Request) {
	cookie, err := r.Cookie("admin_session")
	if err != nil || cookie.Value != "authenticated" {
		http.Error(w, "Unauthorized", http.StatusUnauthorized)
		return
	}

	file, fileHeader, err := r.FormFile("file")
	if err != nil {
		http.Redirect(w, r, "/admin?status=error", http.StatusSeeOther)
		return
	}
	defer file.Close()

	ext := strings.ToLower(filepath.Ext(fileHeader.Filename))
	var rows [][]string

	if ext == ".xlsx" || ext == ".xls" {
		xlFile, err := excelize.OpenReader(file)
		if err != nil {
			http.Redirect(w, r, "/admin?status=invalid_file", http.StatusSeeOther)
			return
		}
		sheets := xlFile.GetSheetList()
		if len(sheets) == 0 {
			http.Redirect(w, r, "/admin?status=invalid_file", http.StatusSeeOther)
			return
		}
		xlRows, _ := xlFile.GetRows(sheets[0])
		rows = xlRows
	} else if ext == ".csv" {
		csvReader := csv.NewReader(file)
		csvRows, err := csvReader.ReadAll()
		if err != nil {
			http.Redirect(w, r, "/admin?status=invalid_file", http.StatusSeeOther)
			return
		}
		rows = csvRows
	} else {
		http.Redirect(w, r, "/admin?status=unsupported", http.StatusSeeOther)
		return
	}

	if len(rows) < 2 {
		http.Redirect(w, r, "/admin?status=empty_file", http.StatusSeeOther)
		return
	}

	headers := rows[0]
	idxLoc := findColIndex(headers, []string{"محل", "شهر", "دفتر", "کارخانه"}, 0)
	idxUnit := findColIndex(headers, []string{"واحد", "بخش", "دپارتمان"}, 1)
	idxName := findColIndex(headers, []string{"نام", "شخص", "مخاطب"}, 2)
	idxP1 := findColIndex(headers, []string{"تلفن 1", "تلفن اول", "اصلی", "موبایل"}, 3)
	idxP2 := findColIndex(headers, []string{"تلفن 2", "تلفن دوم", "داخلی", "ثابت"}, 4)

	successCount, failedCount := 0, 0
	tx, _ := db.Begin()

	for _, r := range rows[1:] {
		getVal := func(idx int) string {
			if idx >= 0 && idx < len(r) {
				val := strings.TrimSpace(r[idx])
				if strings.ToLower(val) == "none" || strings.ToLower(val) == "nan" || strings.ToLower(val) == "null" {
					return ""
				}
				return val
			}
			return ""
		}

		loc := getVal(idxLoc)
		unit := getVal(idxUnit)
		name := getVal(idxName)
		p1 := getVal(idxP1)
		p2 := getVal(idxP2)

		if loc == "" {
			loc = "نامشخص"
		}
		if unit == "" {
			unit = "نامشخص"
		}

		if name != "" {
			_, err = tx.Exec("INSERT INTO contacts (location, unit, name, phone1, phone2) VALUES (?, ?, ?, ?, ?)",
				loc, unit, name, p1, p2)
			if err == nil {
				successCount++
			} else {
				failedCount++
			}
		} else {
			if loc != "نامشخص" || unit != "نامشخص" || p1 != "" || p2 != "" {
				failedCount++
			}
		}
	}
	_ = tx.Commit()
	globalLogger.Printf("Excel import finished: %d imported, %d failed", successCount, failedCount)
	http.Redirect(w, r, fmt.Sprintf("/admin?status=imported&success=%d&failed=%d", successCount, failedCount), http.StatusSeeOther)
}

// ==========================================
// Application EntryPoint (main)
// ==========================================
func main() {
	initDB()
	defer db.Close()

	// روترها و پورت‌ها به همراه هندل کردن ROOT_PATH
	mux := http.NewServeMux()
	basePath := strings.TrimRight(ROOT_PATH, "/")

	mux.HandleFunc(basePath+"/", handleMain)
	mux.HandleFunc(basePath+"/api/search", handleAPISearch)
	mux.HandleFunc(basePath+"/api/toggle-theme", handleThemeToggle)
	mux.HandleFunc(basePath+"/login", handleLogin)
	mux.HandleFunc(basePath+"/logout", handleLogout)
	mux.HandleFunc(basePath+"/admin", handleAdmin)
	mux.HandleFunc(basePath+"/admin/credentials", handleAdminCredentials)
	mux.HandleFunc(basePath+"/admin/upload", handleAdminUpload)
	mux.HandleFunc(basePath+"/admin/download-sample", handleDownloadSample)
	mux.HandleFunc(basePath+"/admin/backup", handleBackup)
	mux.HandleFunc(basePath+"/admin/clear", handleAdminClear)

	serverAddr := ":" + PORT
	fmt.Printf("Server starting on http://localhost%s%s/\n", serverAddr, basePath)
	log.Fatal(http.ListenAndServe(serverAddr, mux))
}

// ==========================================
// UI Embedded Templates (HTML/CSS/JS)
// ==========================================

const GLOBAL_STYLES_JS_HEAD = `
	<meta charset="UTF-8">
	<meta name="viewport" content="width=device-width, initial-scale=1.0">
	<script src="https://cdn.tailwindcss.com"></script>
	<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@24,400,0,0" />
	<style>
		@import url('https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@v33.0.0/Vazirmatn-font-face.css');
		body { 
			font-family: 'Vazirmatn', sans-serif !important; 
			direction: rtl; 
			margin: 0; 
			padding: 0; 
			transition: background-color 0.3s ease, color 0.3s ease; 
		} 
		body.body--light { background-color: #f0f2f5; color: #1e293b; }
		body.body--dark { background-color: #121212; color: #cbd5e1; }
		.majlesi-card { 
			border-radius: 12px; 
			box-shadow: 0 8px 24px -4px rgba(0,0,0,0.1); 
			transition: all 0.3s ease; 
		}
		body.body--light .majlesi-card { background-color: #ffffff; }
		body.body--dark .majlesi-card { background-color: #1e1e1e; border: 1px solid #333; }
		.header-bg { background: linear-gradient(90deg, #0f172a 0%, #1e3a8a 100%); color: white; border-bottom: 3px solid #3b82f6; }
		.unit-header { padding: 8px 16px; border-radius: 6px; font-weight: bold; margin-top: 16px; margin-bottom: 8px; }
		body.body--light .unit-header { background-color: #e2e8f0; color: #1e293b; border-right: 4px solid #3b82f6; }
		body.body--dark .unit-header { background-color: #333333; color: #e2e8f0; border-right: 4px solid #60a5fa; }
	</style>
	<script>
		function applyTheme(theme) {
			const body = document.body;
			if (theme === 'true') {
				body.className = 'body--dark';
			} else if (theme === 'false') {
				body.className = 'body--light';
			} else {
				// Auto / System OS Mode
				if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
					body.className = 'body--dark';
				} else {
					body.className = 'body--light';
				}
			}
		}
		function changeTheme(mode) {
			let val = 'null';
			if (mode === 'dark') val = 'true';
			if (mode === 'light') val = 'false';
			fetch('/api/toggle-theme?val=' + val).then(() => {
				applyTheme(val);
			});
		}
	</script>
`

const HTML_TEMPLATE = `
<!DOCTYPE html>
<html lang="fa">
<head>
	` + GLOBAL_STYLES_JS_HEAD + `
	<title>دفترچه تلفن شرکت اکسیرپویان</title>
</head>
<body class="{{.ThemeClass}}">
	<header class="header-bg p-4 flex justify-between items-center shadow-lg">
		<div class="flex items-center gap-3">
			<span class="material-symbols-outlined text-blue-300" style="font-size:36px">contact_phone</span>
			<span class="text-2xl font-bold tracking-wide">دفترچه تلفن شرکت اکسیرپویان</span>
		</div>
		<div class="flex items-center gap-2">
			<!-- منوی تغییر تم -->
			<div class="relative inline-block text-left group">
				<button class="p-2 rounded-full hover:bg-white/10 text-white">
					<span class="material-symbols-outlined">palette</span>
				</button>
				<div class="absolute left-0 hidden group-hover:block bg-white dark:bg-zinc-800 text-black dark:text-white rounded shadow-lg min-w-[140px] z-50">
					<button onclick="changeTheme('light')" class="w-full text-right px-4 py-2 hover:bg-gray-100 dark:hover:bg-zinc-700 font-bold text-sm">روشن (Light)</button>
					<button onclick="changeTheme('dark')" class="w-full text-right px-4 py-2 hover:bg-gray-100 dark:hover:bg-zinc-700 font-bold text-sm">تاریک (Dark)</button>
					<button onclick="changeTheme('auto')" class="w-full text-right px-4 py-2 hover:bg-gray-100 dark:hover:bg-zinc-700 font-bold text-sm">سیستم (Auto)</button>
				</div>
			</div>
			
			<a href="/admin/backup" class="bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded-full font-bold shadow-md flex items-center gap-1 text-sm">
				<span class="material-symbols-outlined text-sm">download</span> دریافت فایل اکسل
			</a>
			<a href="/admin" class="border border-white hover:bg-white/10 text-white px-4 py-2 rounded-full font-bold flex items-center gap-1 text-sm">
				<span class="material-symbols-outlined text-sm">admin_panel_settings</span> مدیریت
			</a>
		</div>
	</header>

	<main class="w-full max-w-5xl mx-auto p-4 mt-6 gap-4">
		<!-- باکس سرچ -->
		<div class="w-full p-4 majlesi-card mb-6">
			<div class="relative">
				<span class="absolute inset-y-0 right-0 flex items-center pr-3 text-gray-400">
					<span class="material-symbols-outlined">search</span>
				</span>
				<input id="searchInput" oninput="doSearch()" type="text" placeholder="جستجو بر اساس نام، شماره تلفن، بخش یا محل کار..." 
					class="w-full p-3 pr-10 border dark:border-zinc-700 rounded-lg bg-transparent focus:outline-none focus:ring-2 focus:ring-blue-500" style="direction: rtl; text-align: right;" />
				<button onclick="clearSearch()" class="absolute inset-y-0 left-0 flex items-center pl-3 text-gray-400 hover:text-red-500">
					<span class="material-symbols-outlined">close</span>
				</button>
			</div>
		</div>

		<!-- کانتینر نتایج -->
		<div id="resultsContainer">
			<h2 class="text-xl mb-4 font-bold text-gray-700 dark:text-gray-200">جهت مشاهده شماره تماس‌ها، روی "محل کار" مورد نظر کلیک کنید:</h2>
			{{if not .Contacts}}
				<p class="text-gray-500 italic text-center w-full mt-10 text-lg">هیچ اطلاعاتی در سیستم ثبت نشده است.</p>
			{{else}}
				<!-- تولید آکاردئون‌ها بر اساس ساختار گروهی در فرانت‌اند برای سازگاری سریعتر با جاوااسکریپت -->
				<div class="space-y-4" id="accordionGroup">
					<!-- از دیتای لود شده اولیه در بخش زیر استفاده خواهد شد -->
				</div>
			{{end}}
		</div>
	</main>

	<script>
		// تم پایدار را از روی کوکی خوانده و تایید می‌کنیم
		const cookies = document.cookie.split(';');
		let savedTheme = 'null';
		for(let c of cookies) {
			const [k, v] = c.trim().split('=');
			if(k === 'dark_mode') { savedTheme = v; break; }
		}
		applyTheme(savedTheme);

		// ساختار داده اولیه بارگذاری شده به عنوان منبع دیتای کلاینت
		const initialContacts = [
			{{range .Contacts}} {
				id: {{.ID}},
				location: "{{.Location}}",
				unit: "{{.Unit}}",
				name: "{{.Name}}",
				phone1: "{{.Phone1}}",
				phone2: "{{.Phone2}}"
			}, {{end}}
		];

		function buildDefaultGroupedLayout(contacts) {
			const group = {};
			contacts.forEach(c => {
				if(!group[c.location]) group[c.location] = {};
				if(!group[c.location][c.unit]) group[c.location][c.unit] = [];
				group[c.location][c.unit].push(c);
			});

			let html = "";
			Object.keys(group).forEach((loc, index) => {
				html += `
				<div class="majlesi-card overflow-hidden border-t-4 border-blue-500 mb-3">
					<button onclick="toggleAccordion('acc-${"index"}')" class="w-full flex justify-between items-center p-4 font-bold text-lg text-right hover:bg-gray-100 dark:hover:bg-zinc-800">
						<span class="flex items-center gap-2"><span class="material-symbols-outlined">business</span> ${loc}</span>
						<span class="material-symbols-outlined transform transition-transform" id="icon-acc-${"index"}">expand_more</span>
					</button>
					<div id="acc-${"index"}" class="hidden p-4 border-t dark:border-zinc-800 space-y-4">`;
				
				Object.keys(group[loc]).forEach(unit => {
					html += `
						<div>
							<div class="unit-header text-md mb-2">${unit}</div>
							<div class="overflow-x-auto">
								<table class="w-full text-right text-sm border-collapse">
									<thead>
										<tr class="bg-gray-50 dark:bg-zinc-800 text-gray-700 dark:text-gray-300">
											<th class="p-3 border-b dark:border-zinc-700">نام و نام خانوادگی</th>
											<th class="p-3 border-b dark:border-zinc-700">تلفن اصلی</th>
											<th class="p-3 border-b dark:border-zinc-700 text-left">تلفن داخلی/دوم</th>
										</tr>
									</thead>
									<tbody>`;
					group[loc][unit].forEach(c => {
						html += `
										<tr class="hover:bg-gray-100/50 dark:hover:bg-zinc-800/50">
											<td class="p-3 border-b dark:border-zinc-800 font-bold">${c.name}</td>
											<td class="p-3 border-b dark:border-zinc-800 font-medium text-blue-600 dark:text-blue-400">${c.phone1}</td>
											<td class="p-3 border-b dark:border-zinc-800 text-left text-gray-500 font-medium">${c.phone2}</td>
										</tr>`;
					});
					html += `</tbody></table></div></div>`;
				});
				html += `</div></div>`;
			});
			return html;
		}

		function toggleAccordion(id) {
			const el = document.getElementById(id);
			const icon = document.getElementById('icon-' + id);
			if(el.classList.contains('hidden')) {
				el.classList.remove('hidden');
				icon.classList.add('rotate-180');
			} else {
				el.classList.add('hidden');
				icon.classList.remove('rotate-180');
			}
		}

		// بارگذاری ساختار پیش‌فرض
		const container = document.getElementById('accordionGroup');
		if(container) {
			container.innerHTML = buildDefaultGroupedLayout(initialContacts);
		}

		let debounceTimer;
		function doSearch() {
			clearTimeout(debounceTimer);
			const query = document.getElementById('searchInput').value.trim();
			const resContainer = document.getElementById('resultsContainer');
			
			if(!query) {
				resContainer.innerHTML = `
					<h2 class="text-xl mb-4 font-bold text-gray-700 dark:text-gray-200">جهت مشاهده شماره تماس‌ها، روی "محل کار" مورد نظر کلیک کنید:</h2>
					<div class="space-y-4" id="accordionGroup">${buildDefaultGroupedLayout(initialContacts)}</div>
				`;
				return;
			}

			debounceTimer = setTimeout(() => {
				fetch('/api/search?q=' + encodeURIComponent(query))
					.then(r => r.json())
					.then(data => {
						let html = "";
						
						// دکمه بازگشت در بالای نتایج
						html += `
							<div class="w-full flex justify-between items-center mb-4 p-3 bg-blue-50 dark:bg-slate-800 rounded-lg border border-blue-100 dark:border-slate-700">
								<div class="flex items-center gap-2">
									<span class="material-symbols-outlined text-blue-600">search</span>`;
						if(data.direct && data.direct.length > 0) {
							html += `<span class="text-lg font-bold text-blue-800 dark:text-blue-300">نتایج جستجو برای "${query}" (${data.direct.length} مورد)</span>`;
						} else {
							html += `<span class="text-lg font-bold text-amber-800 dark:text-amber-300">جستجوی فازی برای "${query}"</span>`;
						}
						html += `
								</div>
								<button onclick="clearSearch()" class="text-red-500 font-bold hover:underline flex items-center gap-1 text-sm">
									<span class="material-symbols-outlined text-sm">arrow_forward</span> پاک کردن و بازگشت به لیست اصلی
								</button>
							</div>`;

						const list = (data.direct && data.direct.length > 0) ? data.direct : data.fuzzy;
						
						if(list && list.length > 0) {
							if(!data.direct || data.direct.length === 0) {
								html += `<p class="text-md mb-2 text-amber-700 dark:text-amber-400">نتیجه دقیقی یافت نشد؛ نزدیک‌ترین موارد پیشنهادی به عبارت شما:</p>`;
							}
							html += `
								<div class="overflow-x-auto majlesi-card p-4">
									<table class="w-full text-right text-sm border-collapse">
										<thead>
											<tr class="bg-gray-50 dark:bg-zinc-800 text-gray-700 dark:text-gray-300">
												<th class="p-3 border-b dark:border-zinc-700">محل کار</th>
												<th class="p-3 border-b dark:border-zinc-700">واحد / بخش</th>
												<th class="p-3 border-b dark:border-zinc-700">نام و نام خانوادگی</th>
												<th class="p-3 border-b dark:border-zinc-700">تلفن اول</th>
												<th class="p-3 border-b dark:border-zinc-700 text-left">تلفن دوم</th>
											</tr>
										</thead>
										<tbody>`;
							list.forEach(c => {
								html += `
											<tr class="hover:bg-gray-100/50 dark:hover:bg-zinc-800/50">
												<td class="p-3 border-b dark:border-zinc-800 text-gray-500">${c.location}</td>
												<td class="p-3 border-b dark:border-zinc-800 text-gray-500">${c.unit}</td>
												<td class="p-3 border-b dark:border-zinc-800 font-bold">${c.name}</td>
												<td class="p-3 border-b dark:border-zinc-800 font-medium text-blue-600 dark:text-blue-400">${c.phone1}</td>
												<td class="p-3 border-b dark:border-zinc-800 text-left text-gray-500 font-medium">${c.phone2}</td>
											</tr>`;
							});
							html += `</tbody></table></div>`;
						} else {
							html += `
								<div class="w-full flex flex-col items-center justify-center p-8">
									<span class="material-symbols-outlined text-gray-400" style="font-size:64px">search_off</span>
									<p class="text-gray-500 text-lg mt-2">هیچ موردی معادل یا مشابه با "${query}" یافت نشد.</p>
								</div>`;
						}
						resContainer.innerHTML = html;
					});
			}, 300);
		}

		function clearSearch() {
			document.getElementById('searchInput').value = '';
			doSearch();
		}
	</script>
</body>
</html>
`

const LOGIN_TEMPLATE = `
<!DOCTYPE html>
<html lang="fa">
<head>
	` + GLOBAL_STYLES_JS_HEAD + `
	<title>ورود به پنل مدیریت اکسیرپویان</title>
</head>
<body class="body--light dark:body--dark">
	<div class="w-full h-screen flex items-center justify-center">
		<div class="w-96 p-8 majlesi-card flex flex-col items-center gap-4">
			<span class="material-symbols-outlined text-blue-700" style="font-size:56px">shield_person</span>
			<h1 class="text-2xl font-bold text-center">ورود به پنل مدیریت اکسیرپویان</h1>
			
			<form action="/login" method="POST" class="w-full space-y-4">
				<div>
					<label class="block text-sm font-bold mb-1">نام کاربری</label>
					<input type="text" name="username" class="w-full p-2 border rounded focus:outline-none focus:ring-2 focus:ring-blue-500" required />
				</div>
				<div>
					<label class="block text-sm font-bold mb-1">رمز عبور</label>
					<input type="password" name="password" class="w-full p-2 border rounded focus:outline-none focus:ring-2 focus:ring-blue-500" required />
				</div>
				<button type="submit" class="w-full bg-blue-700 hover:bg-blue-800 text-white p-3 rounded-full font-bold text-lg mt-4 shadow-lg">ورود امن</button>
			</form>
			<a href="/" class="text-gray-500 font-bold hover:underline text-sm">بازگشت به دفترچه</a>
		</div>
	</div>
</body>
</html>
`

const ADMIN_TEMPLATE = `
<!DOCTYPE html>
<html lang="fa">
<head>
	` + GLOBAL_STYLES_JS_HEAD + `
	<title>پنل مدیریت اکسیرپویان</title>
</head>
<body class="body--light dark:body--dark">
	<header class="bg-slate-800 p-4 flex justify-between items-center shadow-md border-b-4 border-slate-600 text-white">
		<div class="flex items-center gap-3">
			<span class="material-symbols-outlined text-amber-400" style="font-size:32px">admin_panel_settings</span>
			<span class="text-2xl font-bold">پنل مدیریت اکسیرپویان</span>
		</div>
		<div class="flex items-center gap-2">
			<form action="/logout" method="POST">
				<button type="submit" class="bg-red-500 hover:bg-red-600 text-white px-4 py-2 rounded-full font-bold flex items-center gap-1 text-sm">
					<span class="material-symbols-outlined text-sm">logout</span> خروج امن
				</button>
			</form>
		</div>
	</header>

	<main class="w-full max-w-6xl mx-auto p-6 mt-4 gap-6">
		<div class="grid grid-cols-1 md:grid-cols-3 gap-6 mb-6">
			<!-- بخش آپلود دیتابیس -->
			<div class="col-span-2 majlesi-card p-6 border-t-4 border-green-500">
				<h2 class="text-xl font-bold mb-2">اضافه کردن مخاطبین (آپلود اکسل/CSV)</h2>
				<p class="text-sm mb-6 opacity-70">ردیف‌های بدون فیلد "نام" نادیده گرفته می‌شوند.</p>
				
				<form action="/admin/upload" method="POST" enctype="multipart/form-data" class="space-y-4">
					<input type="file" name="file" accept=".csv, .xlsx, .xls" class="block w-full border dark:border-zinc-700 p-2 rounded" required />
					<div class="flex justify-between items-center mt-4">
						<a href="/admin/download-sample" class="border border-green-600 text-green-600 dark:text-green-400 px-4 py-2 rounded-full font-bold text-sm flex items-center gap-1 hover:bg-green-50">
							<span class="material-symbols-outlined text-sm">grid_on</span> دانلود فایل نمونه
						</a>
						<button type="submit" class="bg-green-600 hover:bg-green-700 text-white px-6 py-2 rounded-full font-bold text-sm flex items-center gap-1">آپلود و بروزرسانی</button>
					</div>
				</form>
				
				<!-- دکمه خطرناک حذف کل دیتابیس -->
				<div class="mt-6 pt-6 border-t dark:border-zinc-800 flex justify-end">
					<form action="/admin/clear" method="POST" onsubmit="return confirm('آیا از حذف کل دیتابیس اطمینان دارید؟');">
						<button type="submit" class="bg-red-600 hover:bg-red-700 text-white px-4 py-2 rounded-full font-bold text-sm flex items-center gap-1">
							<span class="material-symbols-outlined text-sm">delete_sweep</span> حذف کل دیتابیس
						</button>
					</form>
				</div>
			</div>

			<!-- بخش تغییر پسورد -->
			<div class="majlesi-card p-6 border-t-4 border-blue-500">
				<h2 class="text-xl font-bold mb-6">تنظیمات امنیتی ادمین</h2>
				<form action="/admin/credentials" method="POST" class="space-y-4">
					<div>
						<label class="block text-sm font-bold mb-1">نام کاربری جدید</label>
						<input type="text" name="username" class="w-full p-2 border dark:border-zinc-700 bg-transparent rounded focus:outline-none" required />
					</div>
					<div>
						<label class="block text-sm font-bold mb-1">رمز عبور جدید</label>
						<input type="password" name="password" class="w-full p-2 border dark:border-zinc-700 bg-transparent rounded focus:outline-none" required />
					</div>
					<button type="submit" class="w-full bg-blue-600 hover:bg-blue-700 text-white p-3 rounded-full font-bold text-sm mt-4 shadow flex items-center justify-center gap-1">
						<span class="material-symbols-outlined text-sm">save</span> ذخیره اطلاعات ورود
					</button>
				</form>
			</div>
		</div>

		<!-- نمایش کل دیتابیس به صورت جدول -->
		<div class="majlesi-card p-6 border-t-4 border-gray-400">
			<div class="flex justify-between items-center mb-4">
				<h2 class="text-xl font-bold">نمایش جدولی کل اطلاعات دیتابیس</h2>
				<a href="/admin/backup" class="bg-slate-600 hover:bg-slate-700 text-white px-4 py-2 rounded-full font-bold text-sm flex items-center gap-1">
					<span class="material-symbols-outlined text-sm">cloud_download</span> دانلود بکاپ اکسل
				</a>
			</div>
			
			<div class="overflow-x-auto">
				<table class="w-full text-right text-sm border-collapse">
					<thead>
						<tr class="bg-gray-50 dark:bg-zinc-800 text-gray-700 dark:text-gray-300">
							<th class="p-3 border-b dark:border-zinc-700">محل کار</th>
							<th class="p-3 border-b dark:border-zinc-700">واحد / بخش</th>
							<th class="p-3 border-b dark:border-zinc-700">نام و نام خانوادگی</th>
							<th class="p-3 border-b dark:border-zinc-700">تلفن اول</th>
							<th class="p-3 border-b dark:border-zinc-700 text-left">تلفن دوم</th>
						</tr>
					</thead>
					<tbody>
						{{range .Contacts}}
						<tr class="hover:bg-gray-100/50 dark:hover:bg-zinc-800/50">
							<td class="p-3 border-b dark:border-zinc-800">{{.Location}}</td>
							<td class="p-3 border-b dark:border-zinc-800">{{.Unit}}</td>
							<td class="p-3 border-b dark:border-zinc-800 font-bold">{{.Name}}</td>
							<td class="p-3 border-b dark:border-zinc-800 text-blue-600 dark:text-blue-400">{{.Phone1}}</td>
							<td class="p-3 border-b dark:border-zinc-800 text-left text-gray-500">{{.Phone2}}</td>
						</tr>
						{{else}}
						<tr>
							<td colspan="5" class="p-6 text-center text-gray-500 italic">هیچ اطلاعاتی در سیستم ثبت نشده است.</td>
						</tr>
						{{end}}
					</tbody>
				</table>
			</div>
		</div>
	</main>
</body>
</html>
`
